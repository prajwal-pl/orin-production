"""Planner-driven read-only local filesystem and browser tools."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import bot, planner, runtime
from orchestration.agents import ModelCapabilities, ProviderResult
from orchestration.local_tools import ToolResult
from orchestration.model_budget import ModelRecord, ModelRouter, TaskBudget
from orchestration.policy import PolicyStore
from orchestration.runtime import Runtime, capability_help
from orchestration.schema import PlannerDecision


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    return path


def _plan(tool: str, arguments: dict | None):
    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", tool=tool, arguments=arguments)
    return plan


def test_tool_catalog_requires_grant_and_approved_root(tmp_path):
    policy = PolicyStore(tmp_path / "policy.db")
    root = tmp_path / "root"
    root.mkdir()
    assert planner.tool_catalog("local", policy) == []
    policy.grant("local", "filesystem", "read")
    assert planner.tool_catalog("local", policy) == []
    policy.grant_root("local", root, "read")
    assert [tool.id for tool in planner.tool_catalog("local", policy)] == ["filesystem_read"]
    policy.grant("local", "browser", "read")
    assert [tool.id for tool in planner.tool_catalog("local", policy)] == [
        "filesystem_read", "browser_fetch"]


@pytest.mark.asyncio
async def test_model_planner_selects_a_local_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: [])
    policy = PolicyStore(tmp_path / "policy.db")
    root = tmp_path / "root"
    root.mkdir()
    policy.grant_root("local", root, "read")
    path = root / "notes.txt"

    async def fake(role, message, **kwargs):
        assert "filesystem_read" in message and "Local read tools" in message
        return ProviderResult(
            "scripted",
            PlannerDecision(action="execute", tool="filesystem_read",
                            arguments={"path": str(path)}),
            ModelCapabilities(structured_output=True, tool_calling=None), 10, 5,
        )

    monkeypatch.setattr(planner, "invoke_result", fake)
    decision = await planner.plan_request(
        "local", f"read {path}", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]), policy=policy,
    )
    assert decision.action == "execute" and decision.tool == "filesystem_read"
    assert decision.arguments == {"path": str(path)}


@pytest.mark.asyncio
async def test_model_planner_requires_explicit_and_clean_tool_arguments(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: [])
    policy = PolicyStore(tmp_path / "policy.db")
    root = tmp_path / "root"
    root.mkdir()
    policy.grant_root("local", root, "read")

    async def missing(role, message, **kwargs):
        return ProviderResult(
            "scripted", PlannerDecision(action="execute", tool="filesystem_read", arguments=None),
            ModelCapabilities(structured_output=True, tool_calling=None), 1, 1,
        )

    monkeypatch.setattr(planner, "invoke_result", missing)
    decision = await planner.plan_request(
        "local", "read that file", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]), policy=policy,
    )
    assert decision.action == "clarify" and "exact path" in decision.message

    async def extra(role, message, **kwargs):
        return ProviderResult(
            "scripted", PlannerDecision(
                action="execute", tool="filesystem_read",
                arguments={"path": str(root / "x"), "unexpected": "value"}),
            ModelCapabilities(structured_output=True, tool_calling=None), 1, 1,
        )

    monkeypatch.setattr(planner, "invoke_result", extra)
    decision = await planner.plan_request(
        "local", "read that file", budget=TaskBudget(3, 1000),
        router=ModelRouter([ModelRecord("scripted")]), policy=policy,
    )
    assert decision.action == "clarify"


def test_capability_help_lists_enabled_local_tools(tmp_path):
    policy = PolicyStore(tmp_path / "policy.db")
    root = tmp_path / "root"
    root.mkdir()
    policy.grant_root("local", root, "read")
    reply = capability_help("local", policy)
    assert "Local read tools" in reply
    assert "Read /absolute/path" in reply
    assert "Fetch https://example.com" not in reply


@pytest.mark.asyncio
async def test_runtime_executes_an_approved_file_read(local_db, monkeypatch, tmp_path):
    service = Runtime(local_db)
    root = tmp_path / "root"
    root.mkdir()
    note = root / "notes.txt"
    note.write_text("synthetic approved content")
    service.policy.grant_root("local", root, "read")
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "filesystem_read", {"path": str(note)}))

    task = await service.submit("local", "tool", f"read {note}")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "synthetic approved content" in result["result"]
    assert "untrusted data" in result["result"].lower()
    assert service.store.get_task(task["id"], "local")["kind"] == "filesystem_read"
    with service.store.connect() as db:
        execution = db.execute("SELECT capability, status FROM executions WHERE task_id=?",
                               (task["id"],)).fetchone()
        artifact = Path(db.execute("SELECT path FROM artifacts WHERE task_id=?",
                                   (task["id"],)).fetchone()[0])
    assert dict(execution) == {"capability": "filesystem.read", "status": "completed"}
    assert artifact.exists() and artifact.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_runtime_rejects_a_file_outside_approved_roots(local_db, monkeypatch, tmp_path):
    service = Runtime(local_db)
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be read")
    service.policy.grant_root("local", root, "read")
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "filesystem_read", {"path": str(outside)}))

    task = await service.submit("local", "tool", f"read {outside}")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "Could not run filesystem_read" in result["result"]
    assert "must not be read" not in result["result"]
    with service.store.connect() as db:
        status = db.execute("SELECT status FROM executions WHERE task_id=?",
                            (task["id"],)).fetchone()[0]
    assert status == "failed"


@pytest.mark.asyncio
async def test_runtime_requires_the_path_to_come_from_the_current_request(local_db, monkeypatch, tmp_path):
    service = Runtime(local_db)
    root = tmp_path / "root"
    root.mkdir()
    note = root / "notes.txt"
    note.write_text("must not be read without an explicit request")
    service.policy.grant_root("local", root, "read")
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "filesystem_read", {"path": str(note)}))

    task = await service.submit("local", "tool", "read something from somewhere")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "exact file path" in result["result"]
    assert "must not be read" not in result["result"]


@pytest.mark.asyncio
async def test_runtime_executes_a_browser_fetch(local_db, monkeypatch):
    service = Runtime(local_db)
    service.policy.grant("local", "browser", "read")
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "browser_fetch", {"url": "https://example.com/page"}))
    monkeypatch.setattr(runtime.IsolatedBrowser, "fetch",
                        lambda self, url, *args, **kwargs: ToolResult(
                            "completed", "<html>synthetic page</html>", 0))

    task = await service.submit("local", "tool", "fetch https://example.com/page")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "synthetic page" in result["result"]
    assert service.store.get_task(task["id"], "local")["kind"] == "browser_fetch"
    with service.store.connect() as db:
        execution = db.execute("SELECT capability, status FROM executions WHERE task_id=?",
                               (task["id"],)).fetchone()
    assert dict(execution) == {"capability": "browser.fetch", "status": "completed"}


@pytest.mark.asyncio
async def test_telegram_executes_a_planned_file_read(local_db, monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    service = Runtime(local_db)
    root = tmp_path / "root"
    root.mkdir()
    note = root / "telegram.txt"
    note.write_text("telegram tool content")
    service.policy.grant_root("123", root, "read")
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "filesystem_read", {"path": str(note)}))

    message = SimpleNamespace(text=f"read {note}", message_id=12, reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_bot_message(update, None)
    assert "telegram tool content" in message.reply_text.await_args.args[0]
    tasks = Runtime(local_db).store.list_tasks("123")
    assert tasks[0]["kind"] == "filesystem_read"


@pytest.mark.asyncio
async def test_delegated_planner_tool_is_denied(local_db, monkeypatch, tmp_path):
    service = Runtime(local_db)
    root = tmp_path / "root"
    root.mkdir()
    note = root / "delegated.txt"
    note.write_text("delegated content")
    service.policy.grant_root("local", root, "read")
    parent = await service.submit("local", "parent", "plan a read")
    spec = service.create_delegation(
        "local", parent["id"], "read a local file", set(),
        max_model_calls=1, max_model_tokens=100,
    )
    monkeypatch.setattr(runtime, "plan_request", _plan(
        "filesystem_read", {"path": str(note)}))

    child = await service.run_delegation("local", spec.id)
    assert child["status"] == "paused"
    task = next(item for item in service.store.list_tasks("local")
                if item["idempotency_key"] == f"delegate:{spec.id}")
    assert task["status"] == "paused" and task["error"] == "PermissionError"
