"""Telegram action listing, execution review, and reconciliation commands."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from orchestration import bot
from orchestration.actions import ActionStore
from orchestration.runtime import Runtime


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123")
    return path


def _update():
    return SimpleNamespace(message=SimpleNamespace(text="/actions", reply_text=AsyncMock()),
                           effective_user=SimpleNamespace(id=123))


def _context(*args):
    return SimpleNamespace(args=list(args))


def _prepared_action(service, owner="123", key="telegram-action-1"):
    service.policy.grant(owner, "calendar.events.create", "write")
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    action = service.actions.prepare(owner, "calendar.events.create", {
        "summary": "Synthetic Telegram review",
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
    }, key)
    service.policy.approve(owner, action["approval_id"])
    return action


@pytest.mark.asyncio
async def test_actions_list_includes_exact_parameters(local_db):
    service = Runtime(local_db)
    action = _prepared_action(service)
    update = _update()
    await bot.telegram_actions(update, _context())
    reply = update.message.reply_text.await_args.args[0]
    assert action["id"] in reply
    assert "calendar.events.create" in reply and "Synthetic Telegram review" in reply


@pytest.mark.asyncio
async def test_run_action_requires_review_then_confirm(local_db, monkeypatch):
    service = Runtime(local_db)
    action = _prepared_action(service)
    monkeypatch.setattr(ActionStore, "execute", AsyncMock(return_value={
        **action, "status": "completed"}))

    update = _update()
    await bot.telegram_run_action(update, _context(action["id"]))
    assert "confirm" in update.message.reply_text.await_args.args[0]

    update = _update()
    await bot.telegram_run_action(update, _context(action["id"], "confirm"))
    assert "completed" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_reconcile_unknown_action(local_db, monkeypatch):
    service = Runtime(local_db)
    action = _prepared_action(service, key="telegram-action-2")
    with service.actions.connect() as db:
        db.execute("UPDATE actions SET status='unknown' WHERE id=?", (action["id"],))
    monkeypatch.setattr(ActionStore, "reconcile", AsyncMock(return_value={
        **action, "status": "completed"}))

    update = _update()
    await bot.telegram_reconcile_action(update, _context(action["id"]))
    assert "completed" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_action_commands_are_owner_scoped(local_db):
    service = Runtime(local_db)
    action = _prepared_action(service, owner="999", key="other-action")
    update = _update()
    await bot.telegram_run_action(update, _context(action["id"], "confirm"))
    assert "not found" in update.message.reply_text.await_args.args[0]
