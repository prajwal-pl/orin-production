"""Serve the exported Next.js control center from the local FastAPI process."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


WEB_OUTPUT = Path(__file__).resolve().parents[1] / "web" / "out"


def attach_web_assets(app: FastAPI) -> None:
    app.mount("/_next", StaticFiles(directory=str(WEB_OUTPUT / "_next"), check_dir=False),
              name="next-assets")

    @app.get("/", include_in_schema=False)
    def control_center_index():
        index = WEB_OUTPUT / "index.html"
        if not index.is_file():
            raise HTTPException(503, "Control center assets are missing; run npm run build in web/")
        return FileResponse(index, media_type="text/html")

    @app.get("/favicon.svg", include_in_schema=False)
    def control_center_favicon():
        favicon = WEB_OUTPUT / "favicon.svg"
        if not favicon.is_file():
            raise HTTPException(404, "Control center favicon is missing")
        return FileResponse(favicon, media_type="image/svg+xml")
