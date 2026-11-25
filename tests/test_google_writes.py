"""Provider-shaped checks for the three narrow approved Google writes."""

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from orchestration import actions
from orchestration.actions import ActionStore
from orchestration.google_writes import calendar_event_id, execute_google_write, reconcile_google_write
from orchestration.policy import PolicyStore


@pytest.mark.asyncio
async def test_calendar_action_claims_once_and_reconciles_provider_id(monkeypatch, tmp_path):
    policy = PolicyStore(tmp_path / "policy.db")
    policy.grant("alice", "calendar.events.create", "write")
    store = ActionStore(tmp_path / "actions.db", policy)
    start = datetime(2026, 12, 1, 10, tzinfo=timezone.utc)
    params = {"summary": "Aurora review", "start": start.isoformat(),
              "end": (start + timedelta(hours=1)).isoformat()}
    action = store.prepare("alice", "calendar.events.create", params, "aurora-1")
    assert store.prepare("alice", "calendar.events.create", params, "aurora-1")["id"] == action["id"]
    with pytest.raises(ValueError):
        store.prepare("alice", "calendar.events.create", {**params, "summary": "Changed"}, "aurora-1")
    policy.approve("alice", action["approval_id"])
    monkeypatch.setattr(actions, "has_refresh_token", lambda owner, source: owner == "alice" and source == "calendar_write")
    async def token(owner, source):
        return "test-token"
    monkeypatch.setattr(actions, "refreshed_access_token", token)
    requests = []
    event_id = calendar_event_id("alice", "aurora-1")

    def provider(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/calendar/v3/calendars/primary/events"
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["id"] == event_id and body["summary"] == "Aurora review"
        return httpx.Response(200, json={"id": event_id})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await store.execute("alice", action["id"], client)
        again = await store.execute("alice", action["id"], client)
    assert result["status"] == again["status"] == "completed"
    assert result["provider_id"] == event_id and len(requests) == 1
    assert policy.get_approval("alice", action["approval_id"])["status"] == "consumed"


@pytest.mark.asyncio
async def test_gmail_send_and_drive_folder_provider_shapes():
    seen = []

    def provider(request):
        seen.append(request)
        assert request.method == "POST"
        if request.url.host == "gmail.googleapis.com":
            assert request.url.path.endswith("/users/me/messages/send")
            raw = json.loads(request.content)["raw"]
            mail = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
            assert "To: teammate@example.test" in mail
            assert "Subject: Aurora update" in mail
            return httpx.Response(200, json={"id": "message-1"})
        assert request.url.path == "/drive/v3/files"
        body = json.loads(request.content)
        assert body["mimeType"] == "application/vnd.google-apps.folder"
        assert body["appProperties"]["orin_action_id"] == calendar_event_id("alice", "folder-1")
        return httpx.Response(200, json={"id": "folder-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        sent = await execute_google_write("gmail.send", {"to": "teammate@example.test",
            "subject": "Aurora update", "body": "The review is ready."}, "token", "alice", "mail-1", client)
        folder = await execute_google_write("drive.folder.create", {"name": "Aurora"},
                                            "token", "alice", "folder-1", client)
    assert sent["provider_id"] == "message-1" and folder["provider_id"] == "folder-1"
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_ambiguous_reconciliation_only_reads_provider():
    event_id = calendar_event_id("alice", "event-2")
    methods = []
    params = {"summary": "Aurora review", "start": "2026-12-01T10:00:00+00:00",
              "end": "2026-12-01T11:00:00+00:00"}

    def provider(request):
        methods.append(request.method)
        assert request.url.path.endswith(event_id)
        return httpx.Response(200, json={"id": event_id, "summary": params["summary"],
                                          "start": {"dateTime": params["start"]},
                                          "end": {"dateTime": params["end"]}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await reconcile_google_write("calendar.events.create", "token", "alice", "event-2", params, client)
    assert result["provider_id"] == event_id and methods == ["GET"]


@pytest.mark.asyncio
async def test_reconcile_rejects_event_with_same_id_but_different_parameters():
    params = {"summary": "Aurora review", "start": "2026-12-01T10:00:00+00:00",
              "end": "2026-12-01T11:00:00+00:00"}
    def provider(request):
        return httpx.Response(200, json={"id": calendar_event_id("alice", "event-2"),
                                          "summary": "Different event",
                                          "start": {"dateTime": params["start"]},
                                          "end": {"dateTime": params["end"]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ValueError, match="does not match"):
            await reconcile_google_write("calendar.events.create", "token", "alice",
                                         "event-2", params, client)
