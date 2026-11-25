"""Browser pairing and cookie authorization through the existing gateway."""

from fastapi.testclient import TestClient

from orchestration import api
from orchestration.runtime import Runtime
from orchestration.web_auth import web_auth


def test_local_browser_pairing_csrf_and_bearer_compatibility(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_API_TOKEN", "legacy-api-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    service = Runtime(tmp_path / "orin.db")
    api.app.dependency_overrides[api.runtime] = lambda: service
    code = web_auth.start_pairing("alice")
    origin = {"Origin": "http://testserver"}
    try:
        with TestClient(api.app) as client:
            assert client.get("/auth/bootstrap").json() == {"pairing_available": True}
            assert client.get("/tasks").status_code == 401
            assert client.post("/auth/pair", headers={"Origin": "https://evil.example"},
                               json={"code": code}).status_code == 403
            assert client.post("/auth/pair", headers=origin, json={"code": "wrong"}).status_code == 403
            paired = client.post("/auth/pair", headers=origin, json={"code": code})
            assert paired.status_code == 200
            assert "httponly" in paired.headers["set-cookie"].lower()
            assert "samesite=strict" in paired.headers["set-cookie"].lower()
            csrf = paired.json()["csrf"]
            assert paired.json()["owner"] == "alice"
            assert client.get("/auth/session").json()["csrf"] == csrf
            assert client.post("/auth/pair", headers=origin, json={"code": code}).status_code == 403

            task_body = {"session_id": "web", "request": "unsupported web test"}
            assert client.post("/tasks", headers=origin, json=task_body).status_code == 403
            assert client.post("/tasks", headers={"Origin": "https://evil.example",
                                                 "X-Orin-CSRF": csrf}, json=task_body).status_code == 403
            created = client.post("/tasks", headers={**origin, "X-Orin-CSRF": csrf},
                                  json=task_body)
            assert created.status_code == 200
            assert client.get("/tasks").json()[0]["id"] == created.json()["id"]
            assert client.get("/tasks", headers={"X-Orin-User": "bob"}).status_code == 403

            bearer = {"Authorization": "Bearer legacy-api-token", "X-Orin-User": "alice"}
            assert client.get("/tasks", headers=bearer).status_code == 200
            assert client.post("/auth/logout", headers={**origin, "X-Orin-CSRF": csrf}).status_code == 200
            assert client.get("/tasks").status_code == 401
            assert client.get("/auth/session").status_code == 401
    finally:
        api.app.dependency_overrides.clear()


def test_untrusted_host_rejected():
    with TestClient(api.app, base_url="http://attacker.invalid") as client:
        assert client.get("/auth/bootstrap").status_code == 400
