# Orin desktop

This Tauri 2 shell runs the same loopback FastAPI service and Next.js static
export as the browser control center. The native launcher starts the frozen
Python sidecar, shows startup/failure state and the browser URL, and can stop or
restart the service. Its **Open workbench** button opens the local UI in a
desktop webview and transfers the one-time pairing code through a URL fragment,
which the UI removes before pairing. The browser URL remains usable with the
code shown by `orchestration.control_center` when run from a terminal.

## Build on this machine

Install Python 3.14, `uv`, Node.js, Rust, and the [Tauri desktop prerequisites](https://v2.tauri.app/start/prerequisites/)
for your operating system. From the repository root:

```bash
uv sync
cd web && npm ci && cd ..
cd desktop && npm ci
npm run build
```

`npm run build` exports the existing Next.js UI, freezes the Python runtime
with PyInstaller, and builds a native Tauri bundle for the current platform.
For a Linux Debian package only, use `npm run sidecar && npx tauri build --bundles deb`.
The frozen runtime is a single architecture-specific sidecar in
`desktop/src-tauri/binaries/`; it and `desktop/build/` are ignored by Git.
Build separately on each target operating system and architecture. The Linux
bundle requires WebKitGTK 4.1 and the Tauri system libraries on the target.

Launch the installed app. The launcher reports when the local service is ready;
open the workbench from there. The workbench and browser use the same owner
database and authorization rules. A generic OS notification is sent for new
pending approvals, completed or paused tasks, and unexpected runtime stops.
Notification polling uses a private, randomly generated API token unless
`ORIN_API_TOKEN` is already set; it does not expose the token to the webview.
Closing the desktop process stops its sidecar. Closing the workbench window
returns to the launcher so the runtime can be stopped or restarted.

The desktop shell adds no second agent implementation. Google OAuth, service
grants, and model configuration follow the same README instructions as the
browser control center. Environment-provided credentials are inherited by the
sidecar. A tray icon is deferred; the launcher remains the explicit lifecycle
control.

## Verification

Run `npm run check` in `desktop/` for Rust type checks. Build the native bundle
and launch it with an isolated `ORIN_DATABASE_PATH` to smoke-test startup,
loopback serving, pairing, and shutdown. Web tests and Python tests remain in
their existing directories.
