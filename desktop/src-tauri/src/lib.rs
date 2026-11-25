use std::collections::{HashMap, HashSet};
use std::net::{TcpListener, TcpStream};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Clone, Serialize)]
struct RuntimeStatus {
    state: String,
    url: Option<String>,
    code: Option<String>,
    detail: Option<String>,
}

impl RuntimeStatus {
    fn new(state: &str, detail: &str) -> Self {
        Self {
            state: state.into(),
            url: None,
            code: None,
            detail: Some(detail.into()),
        }
    }
}

struct DesktopState {
    child: Mutex<Option<CommandChild>>,
    status: Mutex<RuntimeStatus>,
    generation: Mutex<u64>,
}

impl Default for DesktopState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(RuntimeStatus::new(
                "starting",
                "Preparing the local service…",
            )),
            generation: Mutex::new(0),
        }
    }
}

fn publish(app: &AppHandle, status: RuntimeStatus) {
    *app.state::<DesktopState>().status.lock().unwrap() = status.clone();
    let _ = app.emit_to("launcher", "runtime-status", status);
}

fn is_current(app: &AppHandle, generation: u64) -> bool {
    *app.state::<DesktopState>().generation.lock().unwrap() == generation
}

fn free_port() -> Result<u16, String> {
    let socket = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    let port = socket
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    Ok(port)
}

#[derive(Deserialize)]
struct ObservedItem {
    id: String,
    status: String,
}

fn poll_notifications(app: AppHandle, url: String, token: String, owner: String, generation: u64) {
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
    {
        Ok(client) => client,
        Err(_) => return,
    };
    let mut known_tasks: HashMap<String, String> = HashMap::new();
    let mut known_approvals: HashSet<String> = HashSet::new();
    let mut initialized = false;
    while is_current(&app, generation) {
        let tasks = client
            .get(format!("{url}/tasks"))
            .bearer_auth(&token)
            .header("X-Orin-User", &owner)
            .send()
            .and_then(|response| response.error_for_status())
            .and_then(|response| response.json::<Vec<ObservedItem>>());
        let approvals = client
            .get(format!("{url}/approvals"))
            .bearer_auth(&token)
            .header("X-Orin-User", &owner)
            .send()
            .and_then(|response| response.error_for_status())
            .and_then(|response| response.json::<Vec<ObservedItem>>());
        if let (Ok(tasks), Ok(approvals)) = (tasks, approvals) {
            for item in tasks {
                let previous = known_tasks.insert(item.id, item.status.clone());
                if initialized && previous.as_deref() != Some(item.status.as_str()) {
                    let body = match item.status.as_str() {
                        "completed" => {
                            Some("A task finished. Open the workbench to review its result.")
                        }
                        "paused" => {
                            Some("A task paused. Open the workbench to inspect what it needs.")
                        }
                        _ => None,
                    };
                    if let Some(body) = body {
                        let _ = app
                            .notification()
                            .builder()
                            .title("Orin task update")
                            .body(body)
                            .show();
                    }
                }
            }
            for item in approvals {
                if item.status == "pending" && !known_approvals.contains(&item.id) {
                    if initialized {
                        let _ = app
                            .notification()
                            .builder()
                            .title("Orin needs a decision")
                            .body("An action is waiting for your review in the workbench.")
                            .show();
                    }
                    known_approvals.insert(item.id);
                }
            }
            initialized = true;
        }
        for _ in 0..100 {
            if !is_current(&app, generation) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
}

fn start_runtime(app: AppHandle) -> Result<(), String> {
    let port = free_port()?;
    let url = format!("http://127.0.0.1:{port}");
    let owner = std::env::var("ORIN_API_USER").unwrap_or_else(|_| "local".into());
    let token = std::env::var("ORIN_API_TOKEN")
        .unwrap_or_else(|_| format!("{}{}", uuid::Uuid::new_v4(), uuid::Uuid::new_v4()));
    let state = app.state::<DesktopState>();
    let generation = {
        let mut guard = state.generation.lock().unwrap();
        *guard += 1;
        *guard
    };
    let command = app
        .shell()
        .sidecar("orin-runtime")
        .map_err(|error| error.to_string())?
        .args(["--port", &port.to_string()])
        .env("ORIN_API_TOKEN", &token)
        .env("ORIN_API_USER", &owner)
        .set_process_group(true)
        .kill_on_drop(true);
    let (mut receiver, child) = command.spawn().map_err(|error| error.to_string())?;
    *state.child.lock().unwrap() = Some(child);
    publish(
        &app,
        RuntimeStatus {
            state: "starting".into(),
            url: Some(url.clone()),
            code: None,
            detail: Some("Waiting for the local service to start…".into()),
        },
    );

    tauri::async_runtime::spawn(async move {
        let mut port_conflict = false;
        while let Some(event) = receiver.recv().await {
            if !is_current(&app, generation) {
                break;
            }
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    if let Some(code) = line.trim().split("one-time pairing code: ").nth(1) {
                        let code = code.trim().to_string();
                        let app_for_probe = app.clone();
                        let url_for_probe = url.clone();
                        let token_for_probe = token.clone();
                        let owner_for_probe = owner.clone();
                        thread::spawn(move || {
                            let address = format!("127.0.0.1:{port}");
                            for _ in 0..150 {
                                if !is_current(&app_for_probe, generation) {
                                    return;
                                }
                                if TcpStream::connect(&address).is_ok() {
                                    publish(
                                        &app_for_probe,
                                        RuntimeStatus {
                                            state: "ready".into(),
                                            url: Some(url_for_probe.clone()),
                                            code: Some(code),
                                            detail: Some(
                                                "Orin is running on this computer.".into(),
                                            ),
                                        },
                                    );
                                    let app_for_notifications = app_for_probe.clone();
                                    thread::spawn(move || {
                                        poll_notifications(
                                            app_for_notifications,
                                            url_for_probe,
                                            token_for_probe,
                                            owner_for_probe,
                                            generation,
                                        )
                                    });
                                    return;
                                }
                                thread::sleep(Duration::from_millis(100));
                            }
                            if is_current(&app_for_probe, generation) {
                                publish(&app_for_probe, RuntimeStatus::new(
                                    "failed", "The local service did not become ready. Restart it to try again."));
                            }
                        });
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    port_conflict |= line.to_ascii_lowercase().contains("address already in use");
                }
                CommandEvent::Terminated(_) => {
                    *app.state::<DesktopState>().generation.lock().unwrap() += 1;
                    *app.state::<DesktopState>().child.lock().unwrap() = None;
                    let detail = if port_conflict {
                        "The local port is in use. Restart Orin to choose another."
                    } else {
                        "The local service stopped unexpectedly. Restart it to continue."
                    };
                    publish(&app, RuntimeStatus::new("failed", detail));
                    if let Some(window) = app.get_webview_window("workbench") {
                        let _ = window.close();
                    }
                    if let Some(window) = app.get_webview_window("launcher") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                    let _ = app
                        .notification()
                        .builder()
                        .title("Orin runtime stopped")
                        .body("Open Orin to restart the local service.")
                        .show();
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

fn stop(app: &AppHandle) {
    let state = app.state::<DesktopState>();
    *state.generation.lock().unwrap() += 1;
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    if let Some(window) = app.get_webview_window("workbench") {
        let _ = window.close();
    }
    if let Some(window) = app.get_webview_window("launcher") {
        let _ = window.show();
    }
    publish(
        app,
        RuntimeStatus::new("stopped", "The local service is stopped."),
    );
}

#[tauri::command]
fn runtime_status(state: State<'_, DesktopState>) -> RuntimeStatus {
    state.status.lock().unwrap().clone()
}

#[tauri::command]
fn stop_runtime(app: AppHandle) {
    stop(&app);
}

#[tauri::command]
fn restart_runtime(app: AppHandle) -> Result<(), String> {
    stop(&app);
    start_runtime(app)
}

#[tauri::command]
fn open_workbench(app: AppHandle) -> Result<(), String> {
    let status = app.state::<DesktopState>().status.lock().unwrap().clone();
    if status.state != "ready" {
        return Err("The local service is not ready".into());
    }
    let url = status.url.ok_or("The local URL is unavailable")?;
    if let Some(window) = app.get_webview_window("workbench") {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
    } else {
        let target = match status.code {
            Some(code) => format!("{url}/#pair={code}"),
            None => url,
        };
        let parsed = target
            .parse()
            .map_err(|error| format!("Invalid local URL: {error}"))?;
        WebviewWindowBuilder::new(&app, "workbench", WebviewUrl::External(parsed))
            .title("Orin Control Center")
            .inner_size(1280.0, 850.0)
            .min_inner_size(800.0, 600.0)
            .build()
            .map_err(|error| error.to_string())?;
    }
    if let Some(window) = app.get_webview_window("launcher") {
        let _ = window.hide();
    }
    Ok(())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .manage(DesktopState::default())
        .invoke_handler(tauri::generate_handler![
            runtime_status,
            stop_runtime,
            restart_runtime,
            open_workbench
        ])
        .on_window_event(|window, event| {
            if window.label() == "workbench" && matches!(event, tauri::WindowEvent::Destroyed) {
                if let Some(launcher) = window.app_handle().get_webview_window("launcher") {
                    let _ = launcher.show();
                }
            }
        })
        .setup(|app| {
            if let Err(error) = start_runtime(app.handle().clone()) {
                publish(app.handle(), RuntimeStatus::new("failed", &error));
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start Orin desktop");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let state = handle.state::<DesktopState>();
            let child = state.child.lock().unwrap().take();
            if let Some(child) = child {
                let _ = child.kill();
            }
        }
    });
}
