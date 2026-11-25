"""The exported control center shares the gateway origin."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestration import web_assets


def test_static_export_served_from_gateway(monkeypatch, tmp_path):
    output = tmp_path / "out"
    asset = output / "_next" / "static" / "app.js"
    asset.parent.mkdir(parents=True)
    (output / "index.html").write_text("<h1>Local control center</h1>")
    asset.write_text("window.orin = true")
    monkeypatch.setattr(web_assets, "WEB_OUTPUT", output)
    app = FastAPI()
    web_assets.attach_web_assets(app)

    with TestClient(app) as client:
        assert "Local control center" in client.get("/").text
        assert client.get("/_next/static/app.js").text == "window.orin = true"


def test_missing_static_export_reports_build_step(monkeypatch, tmp_path):
    monkeypatch.setattr(web_assets, "WEB_OUTPUT", tmp_path / "missing")
    app = FastAPI()
    web_assets.attach_web_assets(app)

    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 503
        assert "npm run build" in response.json()["detail"]
