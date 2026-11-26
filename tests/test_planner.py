"""Planner, catalog, runtime integration, and delegated permission checks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import bot, planner, runtime
from orchestration.agents import ModelCapabilities, ProviderCallError, ProviderResult
from orchestration.model_budget import ModelRecord, ModelRouter, TaskBudget
from orchestration.runtime import Runtime
from orchestration.schema import PlannerDecision


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    return path


def test_catalog_only_advertises_connected_workflows(monkeypatch):
    monkeypatch.setattr(planner, "connected_sources", lambda owner: ["github", "gmail"])
    assert [item.id for item in planner.capability_catalog("local")] == [
        "github_notifications", "gmail_inbox", "daily_briefing", "follow_up"]

    monkeypatch.setattr(planner, "connected_sources", lambda owner: [])
    assert planner.capability_catalog("local") == []


@pytest.mark.asyncio
async def test_deterministic_fallback_lists_real_examples(monkeypatch):
    monkeypatch.setattr(planner, "connected_sources", lambda owner: ["github"])
    decision = await planner.plan_request(
        "local", "anything new?", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]),
    )
    assert decision.action == "refuse"
    assert "Try:" in decision.message
    assert "Summarize my GitHub notifications" in decision.message
    assert "mock" not in decision.message.lower()


@pytest.mark.asyncio
async def test_no_sources_returns_connection_guidance(monkeypatch):
    monkeypatch.setattr(planner, "connected_sources", lambda owner: [])
    decision = await planner.plan_request(
        "local", "anything new?", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]),
    )
    assert decision.action == "refuse"
    assert "No read source is connected" in decision.message


@pytest.mark.asyncio
async def test_model_planner_selects_a_catalog_workflow(monkeypatch):
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: ["gmail"])
    seen = {}

    async def fake(role, message, **kwargs):
        seen["role"] = role
        seen["prompt"] = message
        return ProviderResult(
            "scripted", PlannerDecision(action="execute", workflow="gmail_inbox"),
            ModelCapabilities(structured_output=True, tool_calling=None), 10, 5,
        )

    monkeypatch.setattr(planner, "invoke_result", fake)
    decision = await planner.plan_request(
        "local", "anything in my inbox?", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]),
    )
    assert decision.action == "execute" and decision.workflow == "gmail_inbox"
    assert seen["role"] == "planner" and "gmail_inbox" in seen["prompt"]


@pytest.mark.asyncio
async def test_model_planner_rejects_an_invented_workflow(monkeypatch):
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: ["gmail"])

    async def fake(role, message, **kwargs):
        return ProviderResult(
            "scripted", PlannerDecision(action="execute", workflow="gmail.send"),
            ModelCapabilities(structured_output=True, tool_calling=None), 10, 5,
        )

    monkeypatch.setattr(planner, "invoke_result", fake)
    decision = await planner.plan_request(
        "local", "send an email", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]),
    )
    assert decision.action == "refuse"
    assert "cannot run" in decision.message


@pytest.mark.asyncio
async def test_planner_prompt_redacts_secrets(monkeypatch):
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: ["github"])
    seen = {}

    async def fake(role, message, **kwargs):
        seen["prompt"] = message
        return ProviderResult(
            "scripted", PlannerDecision(action="execute", workflow="github_notifications"),
            ModelCapabilities(structured_output=True, tool_calling=None), 1, 1,
        )

    monkeypatch.setattr(planner, "invoke_result", fake)
    token = "ghp_" + "A" * 30
    await planner.plan_request(
        "local", f"check my notifications with {token}", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]),
    )
    assert token not in seen["prompt"]
    assert "[REDACTED]" in seen["prompt"]


@pytest.mark.asyncio
async def test_runtime_plans_freeform_request_and_persists_kind(local_db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[{
        "repository": "owner/repo", "title": "Please review",
        "reason": "review_requested", "url": "https://github.com/owner/repo/pull/1"}]))

    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", workflow="github_notifications")

    monkeypatch.setattr(runtime, "plan_request", plan)
    service = Runtime(local_db)
    task = await service.submit("local", "planner", "summarize my unread notifications")
    assert task["kind"] == "prototype"
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "Please review" in result["result"]
    stored = service.store.get_task(task["id"], "local")
    assert stored["kind"] == "github_notifications"
    assert service.store.usage_for_task(task["id"]) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action,terminal_kind", [
    ("clarify", "clarification"), ("refuse", "unsupported")])
async def test_runtime_planner_non_execute_completes_honestly(
        local_db, monkeypatch, action, terminal_kind):
    async def plan(owner, request, **kwargs):
        return PlannerDecision(action=action, message="Which source and time range?")

    monkeypatch.setattr(runtime, "plan_request", plan)
    service = Runtime(local_db)
    task = await service.submit("local", "planner", "what needs attention?")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert result["result"] == "Which source and time range?"
    assert service.store.get_task(task["id"], "local")["kind"] == terminal_kind
    assert service.store.usage_for_task(task["id"]) == []


@pytest.mark.asyncio
async def test_planner_failure_pauses_and_resumes(local_db, monkeypatch):
    async def fail(owner, request, **kwargs):
        raise ProviderCallError("no planner model")

    monkeypatch.setattr(runtime, "plan_request", fail)
    service = Runtime(local_db)
    task = await service.submit("local", "planner", "summarize my unread notifications")
    paused = await service.run("local", task["id"])
    assert paused["status"] == "paused" and paused["error"] == "ProviderCallError"
    assert paused["worker_pid"] is None

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[{
        "repository": "owner/repo", "title": "Resumed item",
        "reason": "mention", "url": "https://github.com/owner/repo/issues/2"}]))

    async def execute(owner, request, **kwargs):
        return PlannerDecision(action="execute", workflow="github_notifications")

    monkeypatch.setattr(runtime, "plan_request", execute)
    resumed = await service.run("local", task["id"])
    assert resumed["status"] == "completed"
    assert "Resumed item" in resumed["result"]


@pytest.mark.asyncio
async def test_telegram_freeform_uses_the_planner(local_db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "123")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[{
        "repository": "owner/repo", "title": "Telegram planner item",
        "reason": "assign", "url": "https://github.com/owner/repo/issues/3"}]))

    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", workflow="github_notifications")

    monkeypatch.setattr(runtime, "plan_request", plan)
    message = SimpleNamespace(text="summarize my unread notifications", message_id=7,
                              reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_bot_message(update, None)
    assert "Telegram planner item" in message.reply_text.await_args.args[0]
    tasks = Runtime(local_db).store.list_tasks("123")
    assert tasks[0]["kind"] == "github_notifications"


@pytest.mark.asyncio
async def test_telegram_planner_failure_returns_a_paused_reply(local_db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")

    async def fail(owner, request, **kwargs):
        raise ProviderCallError("no planner model")

    monkeypatch.setattr(runtime, "plan_request", fail)
    message = SimpleNamespace(text="summarize my unread notifications", message_id=8,
                              reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_bot_message(update, None)
    reply = message.reply_text.await_args.args[0]
    assert "is paused" in reply and "no model is available" in reply


@pytest.mark.asyncio
async def test_delegated_planner_cannot_expand_capabilities(local_db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    service = Runtime(local_db)
    parent = await service.submit("local", "parent", "Summarize my GitHub notifications")
    spec = service.create_delegation(
        "local", parent["id"], "what changed overnight?",
        {"github.notifications.read"}, max_model_calls=1, max_model_tokens=100,
    )

    fetched = AsyncMock(return_value=[])
    monkeypatch.setattr(runtime, "fetch_source", fetched)

    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", workflow="gmail_inbox")

    monkeypatch.setattr(runtime, "plan_request", plan)
    child = await service.run_delegation("local", spec.id)
    assert child["status"] == "paused"
    task = next(item for item in service.store.list_tasks("local")
                if item["idempotency_key"] == f"delegate:{spec.id}")
    assert task["status"] == "paused" and task["error"] == "PermissionError"
    fetched.assert_not_awaited()


@pytest.mark.asyncio
async def test_delegated_planner_allows_a_permitted_workflow(local_db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(runtime, "fetch_notifications", AsyncMock(return_value=[{
        "repository": "owner/repo", "title": "Delegated planner item",
        "reason": "mention", "url": "https://github.com/owner/repo/issues/4"}]))
    service = Runtime(local_db)
    parent = await service.submit("local", "parent", "Summarize my GitHub notifications")
    spec = service.create_delegation(
        "local", parent["id"], "what changed overnight?",
        {"github.notifications.read"}, max_model_calls=1, max_model_tokens=100,
    )

    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", workflow="github_notifications")

    monkeypatch.setattr(runtime, "plan_request", plan)
    child = await service.run_delegation("local", spec.id)
    assert child["status"] == "completed"
    task = next(item for item in service.store.list_tasks("local")
                if item["idempotency_key"] == f"delegate:{spec.id}")
    assert task["status"] == "completed" and task["kind"] == "github_notifications"
    assert "Delegated planner item" in task["result"]
