"""Capability discovery and honest fallback behavior for every channel."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import bot, runtime
from orchestration.runtime import Runtime, capability_help, task_kind


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    return path


def test_help_intents_are_recognized_without_capturing_real_tasks():
    for request in ("what can you do?", "/help", "help", "How can you help me?",
                    "what are your capabilities", "what do you do?"):
        assert task_kind(request) == "help", request
    assert task_kind("help me prepare for my meeting") == "meeting_prep"
    assert task_kind("Summarize my GitHub notifications") == "github_notifications"


def test_capability_help_lists_only_connected_sources(monkeypatch):
    monkeypatch.setattr(runtime, "connected_sources", lambda owner: ["github", "gmail"])
    reply = capability_help("local")
    assert "GitHub" in reply and "Gmail" in reply
    assert "Drive" not in reply and "Calendar" not in reply
    assert "Summarize my GitHub notifications" in reply
    assert "not implemented" in reply
    assert "mock" not in reply.lower()


def test_capability_help_explains_missing_connections(monkeypatch):
    monkeypatch.setattr(runtime, "connected_sources", lambda owner: [])
    reply = capability_help("local")
    assert "No read source is connected" in reply
    assert "README" in reply


@pytest.mark.asyncio
async def test_help_task_completes_without_a_model_call(local_db, monkeypatch):
    monkeypatch.setattr(runtime, "connected_sources", lambda owner: ["github", "calendar"])
    service = Runtime(local_db)
    task = await service.submit("local", "help", "what can you do?")
    result = await service.run("local", task["id"])
    assert result["status"] == "completed"
    assert "GitHub" in result["result"] and "Calendar" in result["result"]
    assert "Prepare me for my next meeting" in result["result"]
    assert service.store.usage_for_task(task["id"]) == []


@pytest.mark.asyncio
async def test_telegram_help_command_is_authorized(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    monkeypatch.setattr(runtime, "connected_sources", lambda owner: ["github"])
    message = SimpleNamespace(text="/help", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123), message=message)
    await bot.telegram_help(update, None)
    assert "read-only workflows" in message.reply_text.await_args.args[0]

    denied = SimpleNamespace(text="/help", reply_text=AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=456), message=denied)
    await bot.telegram_help(update, None)
    assert denied.reply_text.await_args.args == (bot.DENIED_REPLY,)
