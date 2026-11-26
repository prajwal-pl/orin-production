"""Credential-free tests for Telegram approval, cancellation, and schedule controls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import bot
from orchestration.runtime import Runtime


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    return path


def _update(user_id: int = 123, text: str = ""):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id), message=message)


def _context(*args):
    return SimpleNamespace(args=list(args))


def _reply(update):
    return update.message.reply_text.await_args.args[0]


def _approval(service, owner="123", capability="filesystem",
              parameters=None, ttl_seconds=600):
    service.policy.grant(owner, capability, "write")
    return service.policy.request_approval(
        owner, capability, parameters or {"path": "/tmp/orin-approval", "sha256": "abc"},
        ttl_seconds=ttl_seconds)


@pytest.mark.asyncio
async def test_approvals_list_shows_exact_parameters_and_owner_scope(local_db):
    service = Runtime(local_db)
    own = _approval(service, "123")
    other = _approval(service, "999")

    update = _update()
    await bot.telegram_approvals(update, _context())
    reply = _reply(update)
    assert own["id"] in reply
    assert "filesystem" in reply and "Parameters:" in reply
    assert other["id"] not in reply


@pytest.mark.asyncio
async def test_approve_requires_review_then_explicit_confirm(local_db):
    service = Runtime(local_db)
    approval = _approval(service, "123")

    update = _update()
    await bot.telegram_approve(update, _context(approval["id"]))
    first = _reply(update)
    assert "confirm" in first and "/tmp/orin-approval" in first
    assert service.policy.get_approval("123", approval["id"])["status"] == "pending"

    update = _update()
    await bot.telegram_approve(update, _context(approval["id"], "confirm"))
    assert "Approved" in _reply(update)
    assert service.policy.get_approval("123", approval["id"])["status"] == "approved"

    update = _update()
    await bot.telegram_approve(update, _context(approval["id"], "confirm"))
    assert "already approved" in _reply(update)


@pytest.mark.asyncio
async def test_approve_rejects_other_owner_and_expired_approval(local_db, monkeypatch):
    service = Runtime(local_db)
    other = _approval(service, "999")
    update = _update()
    await bot.telegram_approve(update, _context(other["id"], "confirm"))
    assert "not found" in _reply(update)

    approval = _approval(service, "123", ttl_seconds=1)
    monkeypatch.setattr("orchestration.policy.time.time",
                        lambda: approval["expires_at"] + 1)
    update = _update()
    await bot.telegram_approve(update, _context(approval["id"], "confirm"))
    assert "expired" in _reply(update)


@pytest.mark.asyncio
async def test_deny_marks_approval_unavailable(local_db):
    service = Runtime(local_db)
    approval = _approval(service, "123")

    update = _update()
    await bot.telegram_deny(update, _context(approval["id"]))
    assert "Denied" in _reply(update)
    assert service.policy.get_approval("123", approval["id"])["status"] == "denied"

    update = _update()
    await bot.telegram_deny(update, _context(approval["id"]))
    assert "unavailable" in _reply(update)


@pytest.mark.asyncio
async def test_cancel_pending_task_and_refuse_running_task(local_db):
    service = Runtime(local_db)
    pending = service.store.create_task("123", "tg", "pending request", "prototype")
    running = service.store.create_task("123", "tg", "running request", "prototype")
    assert service.store.transition(running["id"], "123", ("pending",), "running")

    update = _update()
    await bot.telegram_cancel(update, _context(pending["id"]))
    assert "cancelled" in _reply(update)
    assert service.store.get_task(pending["id"], "123")["status"] == "cancelled"

    update = _update()
    await bot.telegram_cancel(update, _context(running["id"]))
    assert "Only pending or paused" in _reply(update)
    assert service.store.get_task(running["id"], "123")["status"] == "running"

    update = _update()
    await bot.telegram_cancel(update, _context("missing"))
    assert "not found" in _reply(update)


@pytest.mark.asyncio
async def test_schedules_list_and_cancel_are_owner_scoped(local_db):
    service = Runtime(local_db)
    own = service.schedules.create_daily("123", "tg", "Daily briefing", "UTC", 9, 0)
    other = service.schedules.create_daily("999", "tg", "Other briefing", "UTC", 10, 0)

    update = _update()
    await bot.telegram_schedules(update, _context())
    reply = _reply(update)
    assert own["id"] in reply and "Daily briefing" in reply
    assert other["id"] not in reply

    update = _update()
    await bot.telegram_unschedule(update, _context(own["id"]))
    assert "cancelled" in _reply(update)
    assert service.schedules.get("123", own["id"])["status"] == "cancelled"

    update = _update()
    await bot.telegram_unschedule(update, _context(own["id"]))
    assert "not found" in _reply(update)


@pytest.mark.asyncio
async def test_control_commands_reject_unauthorized_users(local_db):
    update = _update(user_id=456)
    await bot.telegram_approvals(update, _context())
    assert _reply(update) == bot.DENIED_REPLY

    update = _update(user_id=456)
    await bot.telegram_schedules(update, _context())
    assert _reply(update) == bot.DENIED_REPLY


@pytest.mark.asyncio
async def test_help_lists_the_new_commands(local_db):
    update = _update()
    await bot.telegram_help(update, _context())
    reply = _reply(update)
    for command in ("/cancel", "/approvals", "/approve", "/deny", "/schedules", "/unschedule"):
        assert command in reply
