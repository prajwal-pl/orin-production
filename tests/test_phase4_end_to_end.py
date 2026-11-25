"""Fictional Aurora launch scenario through API, runtime, policy, and workers."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from orchestration import actions, runtime
from orchestration.api import app, runtime as runtime_dependency
from orchestration.runtime import Runtime
from orchestration.scheduler import dispatch_due


@pytest.mark.asyncio
async def test_aurora_meeting_search_schedule_delegation_and_ambiguous_write(
        monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_API_TOKEN", "phase4-test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "0")
    monkeypatch.setenv("ORIN_GOOGLE_CLIENT_FILE", str(tmp_path / "no-client.json"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    for source in ("GMAIL", "DRIVE", "CALENDAR"):
        monkeypatch.setenv(f"ORIN_{source}_ALLOWED_USERS", "alice")
        monkeypatch.setenv(f"ORIN_{source}_ACCESS_TOKEN", "fictional-token")
        monkeypatch.setenv(f"ORIN_{source}_ACCOUNT_ID", "alice@example.test")
    for source in ("NOTION", "TODOIST", "SLACK", "MICROSOFT"):
        monkeypatch.delenv(f"ORIN_{source}_TOKEN", raising=False)
        monkeypatch.delenv(f"ORIN_{source}_ALLOWED_USERS", raising=False)

    service = Runtime(tmp_path / "orin.db")
    app.dependency_overrides[runtime_dependency] = lambda: service
    headers = {"Authorization": "Bearer phase4-test-token", "X-Orin-User": "alice"}
    now = datetime.now(timezone.utc).isoformat()

    async def fictional_source(source, owner):
        assert owner == "alice"
        data = {
            "calendar": [{"source": "calendar", "source_id": "event-1", "title": "Aurora launch meeting",
                          "detail": "", "url": "https://calendar.google.com/event?eid=1", "occurred_at": now}],
            "gmail": [{"source": "gmail", "source_id": "mail-1", "title": "Aurora launch questions?",
                       "detail": "Teammate", "url": "https://mail.google.com/mail/u/0/#inbox/1", "occurred_at": now}],
            "drive": [{"source": "drive", "source_id": "file-1", "title": "Aurora launch brief",
                       "detail": "Document", "url": "https://drive.google.com/open?id=1", "occurred_at": now}],
        }
        return data[source]

    monkeypatch.setattr(runtime, "fetch_source", fictional_source)
    try:
        with TestClient(app) as client:
            created = client.post("/tasks", headers=headers, json={"session_id": "aurora",
                "request": "Prepare me for the Aurora launch meeting"})
            assert created.status_code == 200
            task_id = created.json()["id"]
            meeting = client.post(f"/tasks/{task_id}/run", headers=headers)
            assert meeting.status_code == 200 and meeting.json()["status"] == "completed"
            answer = meeting.json()["result"]
            assert "Aurora launch meeting" in answer
            assert "Aurora launch brief" in answer and "Aurora launch questions?" in answer
            assert "https://drive.google.com/" in answer and "https://mail.google.com/" in answer

            hits = client.get("/search", headers=headers, params={"q": "Aurora"})
            assert hits.status_code == 200
            assert {hit["source"] for hit in hits.json()} == {"gmail", "drive", "calendar"}
            assert all(hit["account_id"] == "alice@example.test" and hit["citation"]
                       and hit["content_kind"] == "metadata" for hit in hits.json())

            workspace = tmp_path / "approved"
            workspace.mkdir()
            (workspace / "notes.md").write_text("Aurora launch checklist: verify demo.")
            root = client.post("/policy/roots", headers=headers, json={"path": str(workspace)})
            assert root.status_code == 200
            indexed = client.post("/search/index-local", headers=headers,
                json={"root": str(workspace), "relative_paths": ["notes.md"]})
            assert indexed.status_code == 200 and indexed.json()["indexed"] == 1
            assert client.get("/search", headers=headers,
                              params={"q": "Aurora", "include_content": True}).status_code == 403
            assert client.post("/policy/grants", headers=headers,
                               json={"capability": "search.content", "operation": "read"}).status_code == 200
            content_hits = client.get("/search", headers=headers,
                                      params={"q": "Aurora", "include_content": True})
            assert "filesystem" in {hit["source"] for hit in content_hits.json()}
            assert client.post("/search/index-local", headers=headers,
                json={"root": str(workspace), "relative_paths": ["../secret.md"]}).status_code == 403

            parent = client.post("/tasks", headers=headers,
                                 json={"session_id": "aurora", "request": "Daily briefing"}).json()
            denied = client.post("/delegations", headers=headers, json={
                "parent_task_id": parent["id"], "request": "Show recent Drive files",
                "allowed_capabilities": ["gmail.inbox.read"],
                "max_model_calls": 0, "max_model_tokens": 0})
            assert denied.status_code == 403
            child = client.post("/delegations", headers=headers, json={
                "parent_task_id": parent["id"], "request": "Show my Gmail inbox",
                "allowed_capabilities": ["gmail.inbox.read"],
                "max_model_calls": 0, "max_model_tokens": 0})
            assert child.status_code == 200
            child_id = child.json()["id"]
            run_child = client.post(f"/delegations/{child_id}/run", headers=headers)
            assert run_child.status_code == 200 and run_child.json()["status"] == "completed"
            child_task = service.store.get_task(run_child.json()["child_task_id"], "alice")
            assert child_task["status"] == "completed"
            assert service.store.usage_for_task(child_task["id"]) == []

            scheduled_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            job = client.post("/schedules", headers=headers, json={"session_id": "aurora",
                "request": "Daily briefing", "recurrence": "once", "run_at": scheduled_at})
            assert job.status_code == 200
            first = await dispatch_due(service.schedules, service)
            second = await dispatch_due(service.schedules, service)
            assert len(first) == 1 and first[0]["status"] == "completed" and second == []

            grant = client.post("/policy/grants", headers=headers,
                json={"capability": "calendar.events.create", "operation": "write"})
            assert grant.status_code == 200
            start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
            parameters = {"summary": "Aurora launch review", "start": start.isoformat(),
                          "end": (start + timedelta(hours=1)).isoformat()}
            action = client.post("/actions", headers=headers, json={"capability": "calendar.events.create",
                "parameters": parameters, "idempotency_key": "aurora-review-1"})
            assert action.status_code == 200
            action_id = action.json()["id"]
            assert client.post(f"/actions/{action_id}/run", headers=headers).status_code == 400
            approval_id = action.json()["approval_id"]
            assert client.post(f"/approvals/{approval_id}/approve", headers=headers).status_code == 200

            calls = []
            monkeypatch.setattr(actions, "has_refresh_token", lambda owner, source: True)
            async def token(owner, source):
                return "write-token"
            monkeypatch.setattr(actions, "refreshed_access_token", token)
            async def ambiguous(*args, **kwargs):
                calls.append("post")
                raise TimeoutError("Response lost after provider may have committed")
            monkeypatch.setattr(actions, "execute_google_write", ambiguous)
            first_write = client.post(f"/actions/{action_id}/run", headers=headers)
            assert first_write.status_code == 200 and first_write.json()["status"] == "unknown"
            second_write = client.post(f"/actions/{action_id}/run", headers=headers)
            assert second_write.status_code == 200 and second_write.json()["status"] == "unknown"
            assert calls == ["post"]
            async def found(*args, **kwargs):
                return {"provider_id": "calendar-event-1", "status": "created"}
            monkeypatch.setattr(actions, "reconcile_google_write", found)
            reconciled = client.post(f"/actions/{action_id}/reconcile", headers=headers)
            assert reconciled.status_code == 200 and reconciled.json()["status"] == "completed"
            audit = client.get("/policy/audit", headers=headers).json()
            assert {entry["status"] for entry in audit if entry["details"] == approval_id} >= {
                "approval_requested", "approval_approved", "authorized"}
            assert client.post(f"/approvals/{approval_id}/approve", headers=headers).status_code == 403
            assert client.get("/actions", headers={**headers, "X-Orin-User": "bob"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
