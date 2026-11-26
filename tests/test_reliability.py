"""Reliability checks for interrupted runs, shared SQLite stores, and API bounds."""

import asyncio
import os
import sqlite3

import pytest

from orchestration import runtime
from orchestration.runtime import Runtime


@pytest.fixture
def local_db(tmp_path, monkeypatch):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    return path


@pytest.mark.asyncio
async def test_cancelled_run_releases_claim_and_can_resume(local_db, monkeypatch):
    started = asyncio.Event()

    async def blocking_fetch():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "fetch_notifications", blocking_fetch)
    service = Runtime(local_db)
    task = await service.submit("local", "cancel", "Summarize my GitHub notifications")
    worker = asyncio.create_task(service.run("local", task["id"]))
    await asyncio.wait_for(started.wait(), timeout=5)

    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    paused = service.store.get_task(task["id"], "local")
    assert paused["status"] == "paused"
    assert paused["error"] == "Cancelled"
    assert paused["worker_pid"] is None
    assert "interrupted" in runtime.task_reply(paused).lower()

    async def one_item():
        return [{"repository": "owner/repo", "title": "Please review",
                 "reason": "review_requested", "url": "https://github.com/owner/repo/pull/1"}]

    monkeypatch.setattr(runtime, "fetch_notifications", one_item)
    resumed = await Runtime(local_db).run("local", task["id"])
    assert resumed["status"] == "completed"
    assert "Please review" in resumed["result"]


@pytest.mark.asyncio
async def test_stale_running_claim_from_this_process_is_recovered(local_db, monkeypatch):
    async def no_notifications():
        return []

    monkeypatch.setattr(runtime, "fetch_notifications", no_notifications)
    service = Runtime(local_db)
    task = await service.submit("local", "stale", "Summarize my GitHub notifications")
    assert service.store.transition(task["id"], "local", ("pending",), "running")
    with service.store.connect() as db:
        db.execute("UPDATE tasks SET worker_pid=? WHERE id=?", (os.getpid(), task["id"]))

    result = await Runtime(local_db).run("local", task["id"])
    assert result["status"] == "completed"
    assert "no unread GitHub notifications" in result["result"]


@pytest.mark.asyncio
async def test_second_run_does_not_steal_an_active_claim(local_db, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_fetch():
        started.set()
        await release.wait()
        return [{"repository": "owner/repo", "title": "Mention",
                 "reason": "mention", "url": "https://github.com/owner/repo/issues/2"}]

    monkeypatch.setattr(runtime, "fetch_notifications", blocking_fetch)
    service = Runtime(local_db)
    task = await service.submit("local", "concurrent", "Summarize my GitHub notifications")
    worker = asyncio.create_task(service.run("local", task["id"]))
    await asyncio.wait_for(started.wait(), timeout=5)

    second = await service.run("local", task["id"])
    assert second["status"] == "running"

    release.set()
    completed = await asyncio.wait_for(worker, timeout=5)
    assert completed["status"] == "completed"
    assert "Mention" in completed["result"]


@pytest.mark.asyncio
async def test_delegation_timeout_pauses_child_and_allows_resume(local_db, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    started = asyncio.Event()

    async def slow_fetch():
        started.set()
        await asyncio.sleep(5)
        return [{"repository": "owner/repo", "title": "Delegated item",
                 "reason": "assign", "url": "https://github.com/owner/repo/issues/3"}]

    monkeypatch.setattr(runtime, "fetch_notifications", slow_fetch)
    service = Runtime(local_db)
    parent = await service.submit("local", "delegate", "Summarize my GitHub notifications")
    spec = service.delegations.create(
        "local", parent["id"], "Summarize my GitHub notifications",
        {"github.notifications.read"}, {"github.notifications.read"},
        max_model_calls=0, max_model_tokens=0,
        parent_max_calls=3, parent_max_tokens=6000, timeout_seconds=1,
    )

    child = await service.run_delegation("local", spec.id)
    assert child["status"] == "paused"
    task = next(item for item in service.store.list_tasks("local")
                if item["idempotency_key"] == f"delegate:{spec.id}")
    assert started.is_set()
    assert task["status"] == "paused"
    assert task["error"] == "Cancelled"
    assert task["worker_pid"] is None

    async def fast_fetch():
        return [{"repository": "owner/repo", "title": "Delegated item",
                 "reason": "assign", "url": "https://github.com/owner/repo/issues/3"}]

    monkeypatch.setattr(runtime, "fetch_notifications", fast_fetch)
    resumed = await service.run_delegation("local", spec.id)
    assert resumed["status"] == "completed"
    assert service.store.get_task(task["id"], "local")["status"] == "completed"


def test_wal_enabled_for_shared_local_stores(tmp_path):
    from orchestration.actions import ActionStore
    from orchestration.policy import PolicyStore
    from orchestration.scheduler import ScheduledJobStore
    from orchestration.store import TaskStore
    from orchestration.sync import SyncStore

    main = tmp_path / "orin.db"
    policy = PolicyStore(tmp_path / "orin-policy.db")
    ActionStore(tmp_path / "orin-actions.db", policy)
    ScheduledJobStore(tmp_path / "orin-schedules.db")
    SyncStore(tmp_path / "orin-sync.db")
    TaskStore(main)

    for path in (main, tmp_path / "orin-policy.db", tmp_path / "orin-actions.db",
                 tmp_path / "orin-schedules.db", tmp_path / "orin-sync.db"):
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
