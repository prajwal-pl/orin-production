"""Frozen entry point; the same FastAPI app serves desktop and browser clients."""

import os
import threading
import time

from orchestration.control_center import main


def _exit_with_parent(pid: int) -> None:
    """Stop the loopback service if the desktop shell disappears.

    A signal-terminated Tauri process cannot run its exit handler, and the
    sidecar would otherwise keep serving an obsolete runtime. Only the desktop
    shell sets ORIN_PARENT_PID; terminal launches keep their normal lifecycle.
    """
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            os._exit(0)
        except PermissionError:
            pass
        time.sleep(2)


if __name__ == "__main__":
    parent = os.getenv("ORIN_PARENT_PID", "").strip()
    if parent.isdigit():
        threading.Thread(target=_exit_with_parent, args=(int(parent),), daemon=True).start()
    main()
