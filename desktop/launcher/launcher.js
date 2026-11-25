const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const elements = {
  status: document.querySelector(".status"),
  title: document.querySelector("#status-title"),
  detail: document.querySelector("#status-detail"),
  open: document.querySelector("#open"),
  restart: document.querySelector("#restart"),
  stop: document.querySelector("#stop"),
  url: document.querySelector("#url"),
  copy: document.querySelector("#copy"),
};

function render(status) {
  const labels = {
    starting: "Starting Orin",
    ready: "Runtime ready",
    stopped: "Runtime stopped",
    failed: "Runtime unavailable",
  };
  elements.status.dataset.state = status.state;
  elements.title.textContent = labels[status.state] ?? "Local runtime";
  elements.detail.textContent =
    status.detail ?? "The local service is ready for requests.";
  elements.url.textContent = status.url ?? "Waiting for runtime";
  elements.open.disabled = status.state !== "ready";
  elements.copy.disabled = !status.url;
  elements.stop.disabled = status.state === "stopped";
}

listen("runtime-status", ({ payload }) => render(payload));
invoke("runtime_status").then(render);
elements.open.addEventListener("click", () =>
  invoke("open_workbench").catch(showError),
);
elements.restart.addEventListener("click", () =>
  invoke("restart_runtime").catch(showError),
);
elements.stop.addEventListener("click", () =>
  invoke("stop_runtime").catch(showError),
);
elements.copy.addEventListener("click", () =>
  navigator.clipboard.writeText(elements.url.textContent),
);

function showError(error) {
  render({ state: "failed", detail: String(error), url: null });
}
