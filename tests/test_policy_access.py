"""API checks for bounded task lists, cached runtime, and revocable grants."""

import pytest
from fastapi.testclient import TestClient

from orchestration import api
from orchestration.runtime import Runtime


@pytest.fixture
def client_with_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ORIN_API_TOKEN", "access-test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    service = Runtime(tmp_path / "orin.db")
    api.app.dependency_overrides[api.runtime] = lambda: service
    headers = {"Authorization": "Bearer access-test-token", "X-Orin-User": "alice"}
    try:
        with TestClient(api.app) as client:
            yield client, service, headers
    finally:
        api.app.dependency_overrides.clear()


def test_task_list_is_bounded_and_stably_paged(client_with_runtime):
    client, service, headers = client_with_runtime
    created = [service.store.create_task("alice", f"page-{index}", f"request {index}", "prototype")
               for index in range(3)]

    first = client.get("/tasks", headers=headers, params={"limit": 2, "offset": 0})
    second = client.get("/tasks", headers=headers, params={"limit": 2, "offset": 2})
    assert first.status_code == 200 and second.status_code == 200
    assert len(first.json()) == 2 and len(second.json()) == 1
    assert {row["id"] for row in first.json()} | {row["id"] for row in second.json()} == {
        task["id"] for task in created}
    assert client.get("/tasks", headers=headers, params={"limit": 0}).status_code == 422
    assert client.get("/tasks", headers=headers, params={"limit": 501}).status_code == 422


def test_owner_grants_can_be_listed_and_revoked(client_with_runtime, tmp_path):
    client, service, headers = client_with_runtime
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    service.policy.grant("alice", "filesystem", "read")
    service.policy.grant_root("alice", workspace, "read")

    grants = client.get("/policy/grants", headers=headers)
    roots = client.get("/policy/roots", headers=headers)
    assert grants.status_code == 200 and roots.status_code == 200
    assert {"capability": "filesystem", "operation": "read"} in grants.json()
    assert {"path": str(workspace.resolve()), "operation": "read"} in roots.json()
    assert client.get("/policy/grants", headers={**headers, "X-Orin-User": "bob"}).status_code == 403

    revoked = client.delete("/policy/grants", headers=headers,
                            params={"capability": "filesystem", "operation": "read"})
    assert revoked.status_code == 200 and revoked.json()["revoked"] is True
    assert client.delete("/policy/grants", headers=headers,
                         params={"capability": "filesystem", "operation": "read"}).status_code == 404
    assert client.delete("/policy/grants", headers=headers,
                         params={"capability": "filesystem", "operation": "execute"}).status_code == 400

    revoked_root = client.delete("/policy/roots", headers=headers,
                                 params={"path": str(workspace), "operation": "read"})
    assert revoked_root.status_code == 200 and revoked_root.json()["revoked"] is True
    assert client.get("/policy/roots", headers=headers).json() == []
    assert client.delete("/policy/roots", headers=headers,
                         params={"path": str(workspace), "operation": "read"}).status_code == 404


def test_api_runtime_is_reused_for_the_same_database(tmp_path, monkeypatch):
    api._RUNTIMES.clear()
    try:
        monkeypatch.setenv("ORIN_DATABASE_PATH", str(tmp_path / "one.db"))
        first = api.runtime()
        assert api.runtime() is first
        monkeypatch.setenv("ORIN_DATABASE_PATH", str(tmp_path / "two.db"))
        assert api.runtime() is not first
    finally:
        api._RUNTIMES.clear()
