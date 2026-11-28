"""Management read models expose only observed, owner-scoped records."""

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from concurrent.futures import ThreadPoolExecutor

from orchestration import api
from orchestration.integrations import SOURCES
from orchestration.runtime import Runtime
from orchestration.store import TaskStore


def test_concurrent_dashboard_runtime_initialization_migrates_once(tmp_path):
    path = tmp_path / "fresh.db"
    with ThreadPoolExecutor(max_workers=12) as pool:
        stores = list(pool.map(lambda _: TaskStore(path), range(12)))
    assert len(stores) == 12
    with stores[0].connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8


def test_usage_and_source_verification_are_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("ORIN_API_TOKEN", "management-test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    service = Runtime(tmp_path / "orin.db")
    alice = service.store.create_task("alice", "alice-session", "Read my inbox", "gmail")
    bob = service.store.create_task("bob", "bob-session", "Read my inbox", "gmail")
    service.store.record_model_call(alice["id"], "model-a", "summary", 12, 3, 50, True)
    service.store.record_model_call(bob["id"], "model-b", "summary", 99, 30, 100, True)
    service.store.record_execution(alice["id"], SOURCES["gmail"].capability, "completed")
    service.store.record_execution(bob["id"], SOURCES["drive"].capability, "completed")
    api.app.dependency_overrides[api.runtime] = lambda: service
    headers = {"Authorization": "Bearer management-test-token", "X-Orin-User": "alice"}
    try:
        with TestClient(api.app) as client:
            assert client.get("/usage").status_code == 401
            assert client.get("/usage", headers={**headers, "X-Orin-User": "bob"}).status_code == 403
            usage = client.get("/usage", headers=headers).json()
            assert [(row["model"], row["calls"], row["input_tokens"]) for row in usage] == [("model-a", 1, 12)]
            sources = {source["key"]: source for source in client.get("/capabilities", headers=headers).json()}
            assert sources["gmail"]["last_success_at"] is not None
            assert sources["drive"]["last_success_at"] is None
            assert all("token" not in source for source in sources.values())
    finally:
        api.app.dependency_overrides.clear()


def test_google_disconnect_requires_owner_and_cannot_mask_env_token(tmp_path, monkeypatch):
    monkeypatch.setenv("ORIN_API_TOKEN", "management-test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    disconnect = AsyncMock()
    monkeypatch.setattr(api, "disconnect_google", disconnect)
    api.app.dependency_overrides[api.runtime] = lambda: Runtime(tmp_path / "orin.db")
    headers = {"Authorization": "Bearer management-test-token", "X-Orin-User": "alice"}
    try:
        with TestClient(api.app) as client:
            assert client.post("/connections/gmail/disconnect").status_code == 401
            assert client.post("/connections/gmail/disconnect", headers={**headers, "X-Orin-User": "bob"}).status_code == 403
            assert client.post("/connections/slack/disconnect", headers=headers).status_code == 404
            monkeypatch.setenv("ORIN_GMAIL_ACCESS_TOKEN", "env-token")
            assert client.post("/connections/gmail/disconnect", headers=headers).status_code == 409
            monkeypatch.delenv("ORIN_GMAIL_ACCESS_TOKEN")
            response = client.post("/connections/gmail/disconnect", headers=headers)
            assert response.json() == {"source": "gmail", "disconnected": True}
            disconnect.assert_awaited_once_with("alice", "gmail")
    finally:
        api.app.dependency_overrides.clear()
