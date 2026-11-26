import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import agents, runtime
from orchestration.runtime import Runtime


@pytest.fixture
def phase2_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "scripted:backup")
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "3")
    monkeypatch.setenv("ORIN_TASK_MODEL_TOKENS", "6000")
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    return path


def notifications():
    return [
        {"repository": "sample/repo", "title": f"Review item {number}",
         "reason": "review_requested", "url": f"https://github.com/sample/repo/pull/{number}"}
        for number in range(5)
    ]


@pytest.mark.asyncio
async def test_model_summary_records_usage_and_private_artifact(phase2_env, monkeypatch):
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=notifications()))
    agent = SimpleNamespace(ainvoke=AsyncMock(return_value={
        "structured_response": {"summary": "Review the five requested changes."},
        "messages": [SimpleNamespace(usage_metadata={"input_tokens": 120, "output_tokens": 30})],
    }))
    monkeypatch.setattr(agents, "build_agent", lambda role, model: agent)
    service = Runtime(phase2_env)
    task = await service.submit("local", "phase2", "Summarize my GitHub notifications")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "Suggested focus" in completed["result"]
    assert "https://github.com/sample/repo/pull/0" in completed["result"]
    usage = service.store.usage_for_task(task["id"])
    assert len(usage) == 1 and usage[0]["input_tokens"] == 120
    assert json.loads(completed["budget_state"])["calls_used"] == 1
    assert service.store.model_health("scripted:primary") is not None
    with service.store.connect() as db:
        artifact = Path(db.execute("SELECT path FROM artifacts WHERE task_id=?", (task["id"],)).fetchone()[0])
    assert artifact.exists() and artifact.stat().st_mode & 0o777 == 0o600
    agent.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limit_switches_model_and_records_both_attempts(phase2_env, monkeypatch):
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=notifications()))

    def build(role, model):
        if model == "scripted:primary":
            error = RuntimeError("rate limit")
            error.status_code = 429
            return SimpleNamespace(ainvoke=AsyncMock(side_effect=error))
        return SimpleNamespace(ainvoke=AsyncMock(return_value={
            "structured_response": {"summary": "Review the requests."}, "messages": [],
        }))

    monkeypatch.setattr(agents, "build_agent", build)
    service = Runtime(phase2_env)
    task = await service.submit("local", "phase2", "Summarize my GitHub notifications")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "Model fallback used" in completed["result"]
    assert len(service.store.usage_for_task(task["id"])) == 2
    record = service.store.load_model_records()
    assert any(item["name"] == "scripted:primary" and item["cooldown_until"] > 0 for item in record)


@pytest.mark.asyncio
async def test_exhausted_budget_uses_local_summary(phase2_env, monkeypatch):
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=notifications()))
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "0")
    agent = SimpleNamespace(ainvoke=AsyncMock())
    monkeypatch.setattr(agents, "build_agent", lambda role, model: agent)
    service = Runtime(phase2_env)
    task = await service.submit("local", "phase2", "Summarize my GitHub notifications")
    completed = await service.run("local", task["id"])
    assert completed["status"] == "completed"
    assert "Local summary follows" in completed["result"]
    agent.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_setup_failure_pauses_task(phase2_env, monkeypatch):
    def fail_checkpoint_setup(*args, **kwargs):
        raise OSError("checkpoint unavailable")

    monkeypatch.setattr(runtime.AsyncSqliteSaver, "from_conn_string", fail_checkpoint_setup)
    service = Runtime(phase2_env)
    task = await service.submit("local", "phase2", "Summarize my GitHub notifications")
    paused = await service.run("local", task["id"])
    assert paused["status"] == "paused"
    assert paused["error"] == "OSError"
    assert paused["worker_pid"] is None

@pytest.mark.asyncio
async def test_retrieval_is_owner_scoped_and_context_redacts_secrets(phase2_env):
    from orchestration.context import ContextItem, build_context

    service = Runtime(phase2_env)
    await service.submit("local", "s1", "GitHub review preferences: keep summaries brief")
    await service.submit("another", "s2", "GitHub private token ghp_" + "A" * 30)
    matches = service.store.relevant_messages("local", "GitHub notifications and review")
    assert matches == ["GitHub review preferences: keep summaries brief"]
    packet = build_context(
        "GitHub notifications", "fetch completed",
        [ContextItem("persistent", "Token ghp_" + "B" * 30)], 300, 50,
    )
    assert "ghp_" not in packet.text
    assert "[REDACTED]" in packet.text

@pytest.mark.asyncio
async def test_ollama_backend_uses_native_structured_output(monkeypatch):
    from orchestration.schema import Classification

    raw = SimpleNamespace(usage_metadata={"input_tokens": 11, "output_tokens": 4})
    fake_runnable = SimpleNamespace(ainvoke=AsyncMock(return_value={
        "parsed": Classification(type="other", intent="greeting", arguments={}),
        "raw": raw,
    }))

    class FakeOllama:
        def __init__(self, **kwargs):
            assert kwargs["model"] == "tiny"

        def with_structured_output(self, schema, **kwargs):
            assert kwargs["method"] == "json_schema"
            return fake_runnable

    monkeypatch.setattr(agents, "ChatOllama", FakeOllama)
    result = await agents.LangChainBackend().invoke("classifier", "ollama:tiny", "hello")
    assert result.response.type == "other"
    assert result.input_tokens == 11 and result.output_tokens == 4


def test_usage_api_is_owner_scoped(phase2_env, monkeypatch):
    from fastapi.testclient import TestClient
    from orchestration.api import app

    monkeypatch.setenv("ORIN_API_TOKEN", "test-token")
    monkeypatch.setenv("ORIN_API_USER", "local")
    store = Runtime(phase2_env).store
    task = store.create_task("local", "session", "hello", "prototype")
    store.record_model_call(task["id"], "scripted:primary", "classifier", 10, 3, 2.5, True)
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token", "X-Orin-User": "local"}
    assert client.get(f"/tasks/{task['id']}/usage", headers=headers).json()[0]["input_tokens"] == 10
    assert client.get("/models", headers=headers).status_code == 200
    assert client.get("/models").status_code == 401
    assert client.get("/tasks/missing/usage", headers=headers).status_code == 404
