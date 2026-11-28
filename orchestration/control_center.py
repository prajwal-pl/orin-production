"""Start one loopback server for Orin's API and browser control center."""

import argparse
import os

import uvicorn

from orchestration.api import app
from orchestration.config import load_environment
from orchestration.web_assets import WEB_OUTPUT
from orchestration.web_auth import web_auth


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description="Start the local Orin control center")
    parser.add_argument("--port", type=int, default=int(os.getenv("ORIN_WEB_PORT", "8000")))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if not (WEB_OUTPUT / "index.html").is_file():
        parser.error("Control center is not built; run `npm install && npm run build` in web/")
    owner = os.getenv("ORIN_API_USER", "local")
    code = web_auth.start_pairing(owner)
    print(f"Open http://127.0.0.1:{args.port} and enter this one-time pairing code: {code}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
