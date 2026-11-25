from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from orchestration import api, runtime
from orchestration.runtime import Runtime


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    return path


@pytest.mark.asyncio
async def test_github_checkpoint_resume_skips_completed_fetch(local_db, monkeypatch):
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "user-1")
    notifications = [{"repository": "owner/repo", "title": "Review this", "reason": "review_requested", "url": "https://github.com/notifications"}]
    fetch = AsyncMock(return_value=notifications)
    monkeypatch.setattr(runtime, "fetch_notifications", fetch)
    original_summary = runtime.summarize_notifications
    calls = 0

    def interrupted_summary(items):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated process interruption")
        return original_summary(items)

    monkeypatch.setattr(runtime, "summarize_notifications", interrupted_summary)
    first = Runtime(local_db)
    task = await first.submit("user-1", "session-1", "Summarize my GitHub notifications")
    paused = await first.run("user-1", task["id"])
    assert paused["status"] == "paused"
    assert fetch.await_count == 1

    resumed = await Runtime(local_db).run("user-1", task["id"])
    assert resumed["status"] == "completed"
    assert "Review this" in resumed["result"]
    assert "Attention" in resumed["result"]
    assert fetch.await_count == 1
    with pytest.raises(KeyError):
        await Runtime(local_db).run("user-2", task["id"])


@pytest.mark.asyncio
async def test_duplicate_submission_and_session_ownership(local_db):
    service = Runtime(local_db)
    first = await service.submit("alice", "a", "request", "same")
    second = await service.submit("alice", "a", "request", "same")
    assert first["id"] == second["id"]
    with pytest.raises(PermissionError):
        await service.submit("bob", "a", "request")
    assert len(service.store.events(first["id"])) == 1


def test_authenticated_api_task_flow(local_db, monkeypatch):
    from orchestration import nodes
    from orchestration.schema import Classification

    async def classify_other(role, message):
        return Classification(type="other", intent="unsupported", arguments={})

    monkeypatch.setattr(nodes, "invoke_structured", classify_other)
    monkeypatch.setenv("ORIN_API_TOKEN", "test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    client = TestClient(api.app)
    assert client.get("/tasks").status_code == 401
    headers = {"Authorization": "Bearer test-token", "X-Orin-User": "alice"}
    response = client.post("/tasks", headers=headers, json={"session_id": "api", "request": "unsupported request"})
    assert response.status_code == 200
    task_id = response.json()["id"]
    result = client.post(f"/tasks/{task_id}/run", headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    assert "mock actions only" in result.json()["result"]
    assert client.get(f"/tasks/{task_id}", headers={**headers, "X-Orin-User": "bob"}).status_code == 403
    assert client.get("/tasks", headers=headers).json()[0]["id"] == task_id

@pytest.mark.asyncio
async def test_github_fetch_uses_unread_endpoint_and_redacts_token(monkeypatch):
    import httpx
    from orchestration import github

    monkeypatch.setenv("GITHUB_TOKEN", "test-secret")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=[{
            "repository": {"full_name": "owner/repo"},
            "subject": {"title": "Review this", "url": "https://api.github.com/repos/owner/repo/pulls/4"},
            "reason": "review_requested",
        }])

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs))
    items = await github.fetch_notifications()
    assert len(requests) == 1
    assert requests[0].url.params["all"] == "false"
    assert requests[0].url.params["per_page"] == "50"
    assert requests[0].headers["Authorization"] == "Bearer test-secret"
    assert items[0]["url"] == "https://github.com/owner/repo/pull/4"
    assert "test-secret" not in str(items)


def test_sessions_and_messages_api(local_db, monkeypatch):
    monkeypatch.setenv("ORIN_API_TOKEN", "test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    headers = {"Authorization": "Bearer test-token", "X-Orin-User": "alice"}
    client = TestClient(api.app)
    client.post("/tasks", headers=headers, json={"session_id": "my-session", "request": "hello"})
    assert client.get("/sessions", headers=headers).json()[0]["id"] == "my-session"
    messages = client.get("/sessions/my-session/messages", headers=headers).json()
    assert messages[0]["content"] == "hello"
    assert client.get("/sessions/elsewhere/messages", headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_orphaned_running_task_can_resume(local_db, monkeypatch):
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "user")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[]))
    service = Runtime(local_db)
    task = await service.submit("user", "s", "GitHub notifications")
    service.store.transition(task["id"], "user", ("pending",), "running")
    with service.store.connect() as db:
        db.execute("UPDATE tasks SET worker_pid=? WHERE id=?", (99999999, task["id"]))
    result = await Runtime(local_db).run("user", task["id"])
    assert result["status"] == "completed"

@pytest.mark.asyncio
async def test_telegram_github_notifications_entry_point(local_db, monkeypatch):
    from types import SimpleNamespace
    from orchestration import bot

    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "123")
    fetch = AsyncMock(return_value=[{
        "repository": "owner/repo", "title": "Please review", "reason": "review_requested",
        "url": "https://github.com/owner/repo/pull/4",
    }])
    monkeypatch.setattr(runtime, "fetch_notifications", fetch)
    message = SimpleNamespace(text="Summarize GitHub notifications", message_id=42, reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_bot_message(update, None)
    assert "Please review" in message.reply_text.await_args.args[0]
    assert fetch.await_count == 1
    await bot.telegram_bot_message(update, None)
    assert fetch.await_count == 1
    assert len(Runtime(local_db).store.list_tasks("123")) == 1


def test_api_event_reconnect(local_db, monkeypatch):
    from orchestration import nodes
    from orchestration.schema import Classification

    async def classify_other(role, message):
        return Classification(type="other", intent="unsupported", arguments={})

    monkeypatch.setattr(nodes, "invoke_structured", classify_other)
    monkeypatch.setenv("ORIN_API_TOKEN", "test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    headers = {"Authorization": "Bearer test-token", "X-Orin-User": "alice"}
    client = TestClient(api.app)
    task_id = client.post("/tasks", headers=headers,
                          json={"session_id": "s", "request": "other request"}).json()["id"]
    client.post(f"/tasks/{task_id}/run", headers=headers)
    first = client.get(f"/tasks/{task_id}/events", headers=headers).text
    assert "event: created" in first and "event: completed" in first
    latest_id = Runtime(local_db).store.events(task_id)[-1]["id"]
    assert client.get(f"/tasks/{task_id}/events?after={latest_id}", headers=headers).text == ""

@pytest.mark.asyncio
async def test_cli_uses_shared_runtime(local_db, monkeypatch, capsys):
    from orchestration import cli

    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[]))
    await cli.run_command("Summarize GitHub notifications", "cli-test")
    assert "no unread GitHub notifications" in capsys.readouterr().out
    assert len(Runtime(local_db).store.list_tasks("local")) == 1

@pytest.mark.asyncio
async def test_provider_result_normalizes_usage(monkeypatch):
    from types import SimpleNamespace
    from orchestration import agents

    fake = SimpleNamespace(ainvoke=AsyncMock(return_value={
        "structured_response": {"type": "other", "intent": "test", "arguments": {}},
        "messages": [SimpleNamespace(usage_metadata={"input_tokens": 7, "output_tokens": 3})],
    }))
    monkeypatch.setattr(agents, "build_agent", lambda role, model: fake)
    monkeypatch.setenv("ORIN_MODEL", "openrouter:scripted")
    monkeypatch.delenv("ORIN_FALLBACK_MODEL", raising=False)
    result = await agents.invoke_result("classifier", "test")
    assert result.model == "openrouter:scripted"
    assert result.input_tokens == 7 and result.output_tokens == 3
    assert result.capabilities.structured_output is True


def test_ollama_backend_can_be_constructed():
    from orchestration.agents import build_agent

    assert build_agent("classifier", "ollama:llama3.2") is not None

@pytest.mark.asyncio
async def test_telegram_resume_command_after_checkpoint(local_db, monkeypatch):
    from types import SimpleNamespace
    from orchestration import bot

    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "123")
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr(runtime, "fetch_notifications", fetch)
    original_summary = runtime.summarize_notifications
    calls = 0

    def interrupted_once(items):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated interruption")
        return original_summary(items)

    monkeypatch.setattr(runtime, "summarize_notifications", interrupted_once)
    service = Runtime(local_db)
    task = await service.submit("123", "telegram:123", "GitHub notifications")
    assert (await service.run("123", task["id"]))["status"] == "paused"
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_resume_task(update, SimpleNamespace(args=[task["id"]]))
    assert "no unread GitHub notifications" in message.reply_text.await_args.args[0]
    assert fetch.await_count == 1
