"""MCP catalog, planner proposal, confirmation, and API flows."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from orchestration import api, bot, planner, runtime
from orchestration.agents import ModelCapabilities, ProviderResult
from orchestration.mcp_registry import MCPRegistry, UntrustedObservation, clear_describe_cache
from orchestration.model_budget import ModelRecord, ModelRouter, TaskBudget
from orchestration.policy import PolicyStore
from orchestration.runtime import Runtime
from orchestration.schema import PlannerDecision


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    return path


@pytest.fixture
def sample_server(tmp_path):
    script = tmp_path / "sample_mcp_server.py"
    script.write_text(f"""#!{sys.executable}
from mcp.server.mcpserver import MCPServer

server = MCPServer('sample')

@server.tool()
def ping() -> str:
    return 'pong from the sample MCP server'

@server.tool()
def search(query: str) -> str:
    return 'Synthetic search for ' + query

server.run('stdio')
""")
    script.chmod(0o700)
    return script


def _registry(tmp_path, server, *, grant_search=False):
    policy = PolicyStore(tmp_path / "policy.db")
    registry = MCPRegistry(policy)
    registry.register("local", "sample", f"stdio:{server}", ["ping", "search"])
    registry.trust("local", "sample")
    policy.grant("local", "mcp.sample.ping", "read")
    if grant_search:
        policy.grant("local", "mcp.sample.search", "read")
    return policy, registry


@pytest.mark.asyncio
async def test_catalog_exposes_only_no_argument_trusted_granted_tools(tmp_path, sample_server):
    clear_describe_cache()
    policy, registry = _registry(tmp_path, sample_server, grant_search=True)
    try:
        entries = await registry.list_planner_tools("local")
        assert [entry["tool"] for entry in entries] == ["ping"]
    finally:
        clear_describe_cache()


@pytest.mark.asyncio
async def test_planner_selects_a_no_argument_mcp_tool(tmp_path, sample_server, monkeypatch):
    clear_describe_cache()
    policy, registry = _registry(tmp_path, sample_server)
    monkeypatch.setenv("ORIN_PLANNER", "auto")
    monkeypatch.setattr(planner, "connected_sources", lambda owner: [])
    seen = {}

    async def fake(role, message, **kwargs):
        seen["prompt"] = message
        return ProviderResult(
            "scripted",
            PlannerDecision(action="execute", tool="mcp:sample:ping", arguments={}),
            ModelCapabilities(structured_output=True, tool_calling=None), 10, 5,
        )

    monkeypatch.setattr(planner, "invoke_result", fake)
    try:
        decision = await planner.plan_request(
            "local", "ping the sample MCP tool", budget=TaskBudget(3, 1000),
            router=ModelRouter([ModelRecord("scripted")]), policy=policy, mcp=registry,
        )
    finally:
        clear_describe_cache()
    assert decision.action == "execute"
    assert decision.tool == "mcp:sample:ping" and decision.arguments == {}
    assert "mcp:sample:ping" in seen["prompt"]


@pytest.mark.asyncio
async def test_runtime_proposes_then_confirms_real_mcp_call(local_db, sample_server, monkeypatch):
    clear_describe_cache()
    service = Runtime(local_db)
    service.mcp.register("local", "sample", f"stdio:{sample_server}", ["ping"])
    service.mcp.trust("local", "sample")
    service.policy.grant("local", "mcp.sample.ping", "read")

    async def plan(owner, request, **kwargs):
        return PlannerDecision(action="execute", tool="mcp:sample:ping", arguments={})

    monkeypatch.setattr(runtime, "plan_request", plan)
    try:
        task = await service.submit("local", "mcp", "ping the sample MCP tool")
        proposed = await service.run("local", task["id"])
        assert proposed["status"] == "completed"
        assert "requires explicit confirmation" in proposed["result"]
        assert service.store.get_task(task["id"], "local")["kind"] == "mcp_confirmation"
        pending = service.mcp_calls.list_pending("local")
        assert len(pending) == 1 and pending[0]["tool"] == "ping"

        result = await service.confirm_mcp_call("local", pending[0]["id"])
        assert result["status"] == "completed"
        assert "pong from the sample MCP server" in result["text"]
        assert result["untrusted"] is True
        assert service.mcp_calls.get("local", pending[0]["id"])["status"] == "completed"
        with pytest.raises(KeyError):
            await service.confirm_mcp_call("local", pending[0]["id"])
    finally:
        clear_describe_cache()


@pytest.mark.asyncio
async def test_mcp_pending_calls_are_owner_scoped_and_deniable(local_db):
    service = Runtime(local_db)
    pending = service.mcp_calls.create("123", "sample", "ping", {})
    assert service.mcp_calls.list_pending("123")[0]["id"] == pending["id"]
    assert service.mcp_calls.list_pending("456") == []
    with pytest.raises(KeyError):
        service.deny_mcp_call("456", pending["id"])
    service.deny_mcp_call("123", pending["id"])
    assert service.mcp_calls.get("123", pending["id"])["status"] == "denied"
    assert service.mcp_calls.list_pending("123") == []


@pytest.mark.asyncio
async def test_telegram_mcp_list_confirm_and_deny(local_db, monkeypatch):
    service = Runtime(local_db)
    first = service.mcp_calls.create("123", "sample", "ping", {})
    second = service.mcp_calls.create("123", "sample", "ping", {})
    monkeypatch.setattr(Runtime, "confirm_mcp_call", AsyncMock(return_value={
        "status": "completed", "server_id": "sample", "tool": "ping",
        "text": "pong from telegram", "untrusted": True}))

    update = SimpleNamespace(message=SimpleNamespace(text="/mcp", reply_text=AsyncMock()),
                             effective_user=SimpleNamespace(id=123))
    await bot.telegram_mcp_calls(update, SimpleNamespace(args=[]))
    assert first["id"] in update.message.reply_text.await_args.args[0]

    update = SimpleNamespace(message=SimpleNamespace(text="/mcpconfirm", reply_text=AsyncMock()),
                             effective_user=SimpleNamespace(id=123))
    await bot.telegram_mcp_confirm(update, SimpleNamespace(args=[first["id"]]))
    assert "pong from telegram" in update.message.reply_text.await_args.args[0]

    update = SimpleNamespace(message=SimpleNamespace(text="/mcpdeny", reply_text=AsyncMock()),
                             effective_user=SimpleNamespace(id=123))
    await bot.telegram_mcp_deny(update, SimpleNamespace(args=[second["id"]]))
    assert "denied" in update.message.reply_text.await_args.args[0]


def test_mcp_call_api_is_owner_scoped_and_confirmable(local_db, monkeypatch):
    monkeypatch.setenv("ORIN_API_TOKEN", "mcp-test-token")
    monkeypatch.setenv("ORIN_API_USER", "alice")
    service = Runtime(local_db)
    pending = service.mcp_calls.create("alice", "sample", "ping", {})
    api.app.dependency_overrides[api.runtime] = lambda: service
    headers = {"Authorization": "Bearer mcp-test-token", "X-Orin-User": "alice"}
    try:
        with TestClient(api.app) as client:
            listed = client.get("/mcp/calls", headers=headers)
            assert listed.status_code == 200 and listed.json()[0]["id"] == pending["id"]
            assert client.get("/mcp/calls", headers={**headers, "X-Orin-User": "bob"}).status_code == 403
            monkeypatch.setattr(Runtime, "confirm_mcp_call", AsyncMock(return_value={
                "status": "completed", "server_id": "sample", "tool": "ping",
                "text": "pong", "untrusted": True}))
            confirmed = client.post(f"/mcp/calls/{pending['id']}/confirm", headers=headers)
            assert confirmed.status_code == 200 and confirmed.json()["text"] == "pong"
            other = service.mcp_calls.create("alice", "sample", "ping", {})
            denied = client.post(f"/mcp/calls/{other['id']}/deny", headers=headers)
            assert denied.status_code == 200
    finally:
        api.app.dependency_overrides.clear()
