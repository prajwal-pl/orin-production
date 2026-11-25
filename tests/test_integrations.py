from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from orchestration import runtime
from orchestration import integrations
from orchestration import agents
from orchestration.api import app
from orchestration.integrations import fetch_calendar, fetch_drive, fetch_gmail
from orchestration.runtime import Runtime, task_reply
from orchestration.skills import BRIEFING_NAME


@pytest.mark.asyncio
async def test_google_adapters_use_read_only_metadata_requests():
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.url.path.endswith("/messages"):
            assert "q" not in request.url.params
            assert request.url.params.get_list("labelIds") == ["INBOX", "UNREAD"]
            return httpx.Response(200, json={"messages": [{"id": "abc123"}]})
        if request.url.path.endswith("/messages/abc123"):
            assert request.url.params["format"] == "metadata"
            return httpx.Response(200, json={"payload": {"headers": [
                {"name": "Subject", "value": "Budget review"},
                {"name": "From", "value": "Colleague <person@example.com>"},
            ]}})
        if request.url.path.endswith("/drive/v3/files"):
            assert request.url.params["q"] == "trashed = false"
            assert "webViewLink" in request.url.params["fields"]
            return httpx.Response(200, json={"files": [{"id": "file1", "name": "Plan",
                "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://drive.google.com/file1"}]})
        if request.url.path.endswith("/calendar/v3/calendars/primary/events"):
            assert request.url.params["singleEvents"] == "true"
            assert request.url.params["timeMin"].startswith("2026-11-25")
            return httpx.Response(200, json={"items": [{"id": "event1", "summary": "Design review",
                "start": {"dateTime": "2026-11-25T10:00:00Z"},
                "htmlLink": "https://calendar.google.com/event1"}]})
        raise AssertionError(f"Unexpected URL: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        mail = await fetch_gmail("test-token", client)
        files = await fetch_drive("test-token", client)
        events = await fetch_calendar("test-token", client, datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert mail[0].title == "Budget review" and mail[0].source == "gmail"
    assert files[0].url == "https://drive.google.com/file1"
    assert events[0].title == "Design review"
    assert len(requests) == 4


@pytest.fixture
def integration_env(monkeypatch, tmp_path):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GOOGLE_CLIENT_FILE", str(tmp_path / "no-google-client.json"))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    for key in ("GMAIL", "DRIVE", "CALENDAR"):
        monkeypatch.setenv(f"ORIN_{key}_ALLOWED_USERS", "local")
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    for key in ("GMAIL", "DRIVE", "CALENDAR"):
        monkeypatch.setenv(f"ORIN_{key}_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "")
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "0")
    monkeypatch.setenv("ORIN_API_TOKEN", "api-test-token")
    monkeypatch.setenv("ORIN_API_USER", "local")
    return path


@pytest.mark.asyncio
async def test_cross_source_briefing_correction_adoption_and_rollback(integration_env, monkeypatch):
    github = [{"repository": "sample/repo", "title": f"Review {index}",
               "reason": "review_requested", "url": f"https://github.com/sample/repo/pull/{index}"}
              for index in range(15)]
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=github))

    async def fake_source(source, owner):
        assert owner == "local"
        return [{"source": source, "source_id": source, "title": {
            "gmail": "Inbox decision", "drive": "Project plan", "calendar": "Calendar deadline",
        }[source], "detail": "", "url": f"https://example.com/{source}", "occurred_at": ""}]

    monkeypatch.setattr(runtime, "fetch_source", fake_source)
    service = Runtime(integration_env)

    async def run(session):
        task = await service.submit("local", session, "Give me a daily briefing")
        return await service.run("local", task["id"])

    baseline = await run("baseline")
    assert baseline["status"] == "completed"
    assert "Calendar deadline" in baseline["result"]
    assert baseline["result"].index("[gmail]") < baseline["result"].index("[calendar]")
    assert len(service.memory.list("local")) == 1

    client = TestClient(app)
    headers = {"Authorization": "Bearer api-test-token", "X-Orin-User": "local"}
    capabilities = client.get("/capabilities", headers=headers).json()
    assert {item["key"] for item in capabilities if item["configured"]} == {"github", "gmail", "drive", "calendar"}
    correction = client.post(f"/tasks/{baseline['id']}/corrections", headers=headers,
                             json={"content": "Put calendar first"})
    assert correction.status_code == 200
    proposal_id = correction.json()["proposal_id"]
    assert proposal_id
    proposal = client.get(f"/skills/{proposal_id}", headers=headers).json()
    assert proposal["name"] == BRIEFING_NAME and proposal["status"] == "proposed"
    client.post(f"/skills/{proposal_id}/activate", headers=headers).raise_for_status()

    improved = await run("improved")
    assert improved["status"] == "completed"
    assert "Calendar deadline" in improved["result"]
    assert improved["result"].index("[calendar]") < improved["result"].index("[gmail]")
    assert client.get(f"/tasks/{improved['id']}/skill", headers=headers).json()["id"] == proposal_id
    assert len(service.memory.list("local")) == 2

    builtin = next(item for item in client.get("/skills", headers=headers).json()
                   if item["name"] == BRIEFING_NAME and item["kind"] == "builtin")
    client.post(f"/skills/{builtin['id']}/activate", headers=headers).raise_for_status()
    restored = await run("restored")
    assert "Calendar deadline" in restored["result"]
    assert restored["result"].index("[gmail]") < restored["result"].index("[calendar]")
    metrics = {item["id"]: item for item in client.get("/skills/metrics", headers=headers).json()}
    assert metrics[builtin["id"]]["corrections"] == 1
    assert metrics[proposal_id]["success_count"] == 1
    assert metrics[proposal_id]["model_calls"] == 0
    assert client.post("/skills/briefing", headers=headers,
                       json={"source_order": ["calendar", "calendar"]}).status_code == 400
    custom = client.post("/skills/briefing", headers=headers,
                         json={"source_order": ["calendar", "gmail", "drive", "github"]})
    assert custom.status_code == 200 and custom.json()["status"] == "proposed"


def test_saved_briefing_order_can_precede_future_sources(integration_env):
    from orchestration.integrations import summarize_evidence
    from orchestration.skills import validate_briefing

    procedure = validate_briefing({"source_order": ["calendar", "gmail"]})
    items = [{"source": "calendar", "source_id": "c", "title": "Calendar item", "detail": "", "url": ""},
             {"source": "new_source", "source_id": "n", "title": "Future item", "detail": "", "url": ""}]
    result = summarize_evidence(items, source_order=procedure["source_order"])
    assert result.index("Calendar item") < result.index("Future item")


@pytest.mark.asyncio
async def test_direct_google_read_pauses_when_token_missing(integration_env, monkeypatch):
    monkeypatch.delenv("ORIN_GMAIL_ACCESS_TOKEN")
    service = Runtime(integration_env)
    task = await service.submit("local", "mail", "Show my Gmail inbox")
    paused = await service.run("local", task["id"])
    assert paused["status"] == "paused" and paused["error"] == "MissingCredential"
    assert "not connected" in task_reply(paused)
    assert service.store.usage_for_task(task["id"]) == []


@pytest.mark.asyncio
async def test_direct_google_read_requires_explicit_owner_grant(integration_env, monkeypatch):
    monkeypatch.delenv("ORIN_GMAIL_ALLOWED_USERS")
    service = Runtime(integration_env)
    with pytest.raises(PermissionError):
        await service.submit("local", "mail", "Show my Gmail inbox")
    assert service.store.list_tasks("local") == []


@pytest.mark.asyncio
async def test_gmail_http_adapter_runs_through_shared_runtime(integration_env, monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "mail-1"}]})
        if request.url.path.endswith("/messages/mail-1"):
            return httpx.Response(200, json={"payload": {"headers": [
                {"name": "Subject", "value": "Quarterly planning"},
                {"name": "From", "value": "colleague@example.com"},
            ]}})
        raise AssertionError("Unexpected request")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(integrations.httpx, "AsyncClient", lambda **kwargs: original_client(
        **(kwargs | {"transport": httpx.MockTransport(handle)})))
    service = Runtime(integration_env)
    task = await service.submit("local", "mail", "Show my unread Gmail inbox")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "Quarterly planning" in completed["result"]
    assert "mail.google.com" in completed["result"]
    assert service.store.usage_for_task(task["id"]) == []
    assert service.memory.list("local")[0]["provenance"] == f"task:{task['id']}"
    with service.store.connect() as db:
        row = db.execute("SELECT path FROM artifacts WHERE task_id=?", (task["id"],)).fetchone()
    artifact = Path(row["path"])
    assert artifact.exists() and artifact.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_briefing_reports_partial_source_failure(integration_env, monkeypatch):
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[]))

    async def fake_source(source, owner):
        if source == "drive":
            raise httpx.HTTPStatusError("unavailable", request=httpx.Request("GET", "https://example.com"),
                                        response=httpx.Response(503))
        return [{"source": source, "source_id": source, "title": source,
                 "detail": "", "url": "", "occurred_at": ""}]

    monkeypatch.setattr(runtime, "fetch_source", fake_source)
    service = Runtime(integration_env)
    task = await service.submit("local", "brief", "Daily briefing")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "drive: unavailable" in completed["result"]
    assert "[gmail]" in completed["result"] and "[calendar]" in completed["result"]
    with service.store.connect() as db:
        failed = db.execute("SELECT COUNT(*) FROM executions WHERE task_id=? AND capability=? AND status='failed'",
                            (task["id"], "drive.files.metadata.read")).fetchone()[0]
    assert failed == 1


@pytest.mark.asyncio
async def test_generic_read_uses_shared_budgeted_model_path(integration_env, monkeypatch):
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "2")

    async def fake_source(source, owner):
        return [{"source": "gmail", "source_id": str(index), "title": f"Message {index}",
                 "detail": "colleague@example.com", "url": f"https://mail.google.com/{index}",
                 "occurred_at": ""} for index in range(5)]

    monkeypatch.setattr(runtime, "fetch_source", fake_source)
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={
        "structured_response": {"summary": "Review the five messages."},
        "messages": [SimpleNamespace(usage_metadata={"input_tokens": 90, "output_tokens": 18})],
    }))

    def build(role, model):
        assert role == "read_summarizer" and model == "scripted:primary"
        return agent

    monkeypatch.setattr(agents, "build_agent", build)
    service = Runtime(integration_env)
    task = await service.submit("local", "mail", "Show my Gmail inbox")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "Suggested focus: Review the five messages." in completed["result"]
    assert "Message 0" in completed["result"]
    usage = service.store.usage_for_task(task["id"])
    assert len(usage) == 1 and usage[0]["role"] == "read_summarizer"
    assert usage[0]["input_tokens"] == 90


@pytest.mark.asyncio
async def test_briefing_resume_reuses_checkpointed_sources(integration_env, monkeypatch):
    github_fetch = AsyncMock(return_value=[])
    source_fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(runtime, "fetch_notifications", github_fetch)
    monkeypatch.setattr(runtime, "fetch_source", source_fetch)
    original = runtime.summarize_evidence
    calls = 0

    def interrupt_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "summarize_evidence", interrupt_once)
    service = Runtime(integration_env)
    task = await service.submit("local", "brief", "Daily briefing")
    assert (await service.run("local", task["id"]))["status"] == "paused"
    resumed = await Runtime(integration_env).run("local", task["id"])
    assert resumed["status"] == "completed"
    assert github_fetch.await_count == 1
    assert source_fetch.await_count == 3


@pytest.mark.asyncio
async def test_telegram_briefing_uses_same_runtime(integration_env, monkeypatch):
    from orchestration import bot

    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "123")
    for key in ("GMAIL", "DRIVE", "CALENDAR"):
        monkeypatch.setenv(f"ORIN_{key}_ALLOWED_USERS", "123")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[]))

    async def fake_source(source, owner):
        assert owner == "123"
        return ([{"source": "calendar", "source_id": "one", "title": "Planning meeting",
                  "detail": "", "url": "", "occurred_at": ""}] if source == "calendar" else [])

    monkeypatch.setattr(runtime, "fetch_source", fake_source)
    message = SimpleNamespace(text="Daily briefing", message_id=92, reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_bot_message(update, None)
    assert "Planning meeting" in message.reply_text.await_args.args[0]
    assert len(Runtime(integration_env).store.list_tasks("123")) == 1
