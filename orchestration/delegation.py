"""Bounded child work records for selective delegation through the shared runtime."""

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from orchestration.db import connect as sqlite_connect, enable_wal


@dataclass(frozen=True)
class DelegationSpec:
    id: str
    parent_task_id: str
    owner: str
    session_id: str
    request: str
    allowed_capabilities: frozenset[str]
    max_model_calls: int
    max_model_tokens: int
    timeout_seconds: int

    @property
    def idempotency_key(self) -> str:
        return f"delegate:{self.id}"


class DelegationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        enable_wal(self.path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS delegated_tasks (
                    id TEXT PRIMARY KEY, parent_task_id TEXT NOT NULL,
                    owner TEXT NOT NULL, session_id TEXT NOT NULL,
                    request TEXT NOT NULL, allowed_capabilities TEXT NOT NULL,
                    max_model_calls INTEGER NOT NULL, max_model_tokens INTEGER NOT NULL,
                    timeout_seconds INTEGER NOT NULL, status TEXT NOT NULL,
                    child_task_id TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(parent_task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS delegated_parent
                    ON delegated_tasks(owner,parent_task_id);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.path, foreign_keys=True)

    @staticmethod
    def _spec(row: sqlite3.Row) -> DelegationSpec:
        return DelegationSpec(row["id"], row["parent_task_id"], row["owner"],
                              row["session_id"], row["request"],
                              frozenset(json.loads(row["allowed_capabilities"])),
                              row["max_model_calls"], row["max_model_tokens"],
                              row["timeout_seconds"])

    def create(self, owner: str, parent_task_id: str, request: str,
               allowed_capabilities: set[str], parent_capabilities: set[str],
               *, max_model_calls: int, max_model_tokens: int,
               parent_max_calls: int, parent_max_tokens: int,
               timeout_seconds: int = 60) -> DelegationSpec:
        if not request.strip() or len(request) > 2000:
            raise ValueError("Child request must be nonempty and bounded")
        if not allowed_capabilities <= parent_capabilities:
            raise PermissionError("Delegated capabilities exceed parent permissions")
        if max_model_calls < 0 or max_model_tokens < 0 or timeout_seconds < 1 or timeout_seconds > 600:
            raise ValueError("Invalid child budget or timeout")
        if parent_max_calls < 0 or parent_max_tokens < 0:
            raise ValueError("Invalid parent budget")
        now = datetime.now(timezone.utc).isoformat()
        child_id = str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            parent = db.execute("""SELECT session_id,status FROM tasks
                WHERE id=? AND owner=?""", (parent_task_id, owner)).fetchone()
            if parent is None or parent["status"] not in {"pending", "running", "paused"}:
                raise PermissionError("Parent task is unavailable to this owner")
            total = db.execute("""SELECT COALESCE(SUM(max_model_calls),0) AS calls,
                COALESCE(SUM(max_model_tokens),0) AS tokens
                FROM delegated_tasks WHERE owner=? AND parent_task_id=? AND status!='cancelled'""",
                (owner, parent_task_id)).fetchone()
            if total["calls"] + max_model_calls > parent_max_calls or \
                    total["tokens"] + max_model_tokens > parent_max_tokens:
                raise ValueError("Delegated inference exceeds parent budget")
            db.execute("""INSERT INTO delegated_tasks
                (id,parent_task_id,owner,session_id,request,allowed_capabilities,
                 max_model_calls,max_model_tokens,timeout_seconds,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)""",
                (child_id, parent_task_id, owner, parent["session_id"], request,
                 json.dumps(sorted(allowed_capabilities)), max_model_calls,
                 max_model_tokens, timeout_seconds, now, now))
            row = db.execute("SELECT * FROM delegated_tasks WHERE id=?", (child_id,)).fetchone()
        return self._spec(row)

    def get(self, owner: str, child_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM delegated_tasks WHERE id=? AND owner=?",
                             (child_id, owner)).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["allowed_capabilities"] = json.loads(item["allowed_capabilities"])
            return item

    def list_children(self, owner: str, parent_task_id: str) -> list[dict]:
        with self.connect() as db:
            return [self.get(owner, row["id"]) for row in db.execute(
                "SELECT id FROM delegated_tasks WHERE owner=? AND parent_task_id=? ORDER BY created_at,id",
                (owner, parent_task_id))]

    def progress(self, owner: str, parent_task_id: str) -> dict:
        children = self.list_children(owner, parent_task_id)
        counts = {status: 0 for status in ("pending", "running", "paused", "completed", "cancelled")}
        for child in children:
            counts[child["status"]] += 1
        return {"parent_task_id": parent_task_id, "total": len(children), "counts": counts}

    def claim(self, owner: str, child_id: str) -> DelegationSpec | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute("""UPDATE delegated_tasks SET status='running',
                updated_at=? WHERE id=? AND owner=? AND status IN ('pending','paused')""",
                (datetime.now(timezone.utc).isoformat(), child_id, owner)).rowcount
            row = db.execute("SELECT * FROM delegated_tasks WHERE id=? AND owner=?",
                             (child_id, owner)).fetchone()
        return self._spec(row) if changed and row else None

    def finish(self, owner: str, child_id: str, status: str,
               child_task_id: str | None = None) -> bool:
        if status not in {"completed", "paused", "cancelled"}:
            raise ValueError("Invalid delegated task status")
        with self.connect() as db:
            return bool(db.execute("""UPDATE delegated_tasks SET status=?,
                child_task_id=COALESCE(?, child_task_id), updated_at=?
                WHERE id=? AND owner=? AND status='running'""",
                (status, child_task_id, datetime.now(timezone.utc).isoformat(),
                 child_id, owner)).rowcount)

    def cancel(self, owner: str, child_id: str) -> dict | None:
        with self.connect() as db:
            db.execute("""UPDATE delegated_tasks SET status='cancelled',updated_at=?
                WHERE id=? AND owner=? AND status IN ('pending','running','paused')""",
                (datetime.now(timezone.utc).isoformat(), child_id, owner))
        return self.get(owner, child_id)

    def cancel_parent(self, owner: str, parent_task_id: str) -> list[str]:
        children = self.list_children(owner, parent_task_id)
        ids = [child["id"] for child in children if child["status"] in {"pending", "running", "paused"}]
        with self.connect() as db:
            db.execute("""UPDATE delegated_tasks SET status='cancelled', updated_at=?
                WHERE owner=? AND parent_task_id=? AND status IN ('pending','running','paused')""",
                (datetime.now(timezone.utc).isoformat(), owner, parent_task_id))
        return ids


Runner = Callable[[DelegationSpec], Awaitable[dict]]


class Delegator:
    """Calls a supplied shared-runtime runner with the child limits intact.

    The runner must pass ``max_model_calls``, ``max_model_tokens``, and
    ``allowed_capabilities`` to Runtime's enforcement boundary. This class
    records the grant and cancels an in-process runner when requested.
    """

    def __init__(self, store: DelegationStore, runner: Runner):
        self.store = store
        self.runner = runner
        self._active: dict[str, asyncio.Task] = {}

    async def execute(self, owner: str, child_id: str) -> dict:
        spec = self.store.claim(owner, child_id)
        if spec is None:
            existing = self.store.get(owner, child_id)
            if existing is None:
                raise KeyError("Delegation not found")
            return existing
        task = asyncio.create_task(self.runner(spec))
        self._active[child_id] = task
        try:
            result = await asyncio.wait_for(task, timeout=spec.timeout_seconds)
            status = result.get("status", "paused")
            self.store.finish(owner, child_id, "completed" if status == "completed" else "paused",
                              result.get("id"))
        except TimeoutError:
            self.store.finish(owner, child_id, "paused")
        except asyncio.CancelledError:
            self.store.finish(owner, child_id, "cancelled")
        except Exception:
            self.store.finish(owner, child_id, "paused")
        finally:
            self._active.pop(child_id, None)
        return self.store.get(owner, child_id)

    def cancel(self, owner: str, child_id: str) -> dict | None:
        item = self.store.cancel(owner, child_id)
        task = self._active.get(child_id)
        if task is not None:
            task.cancel()
        return item

    def cancel_parent(self, owner: str, parent_task_id: str) -> dict:
        for child_id in self.store.cancel_parent(owner, parent_task_id):
            task = self._active.get(child_id)
            if task is not None:
                task.cancel()
        return self.store.progress(owner, parent_task_id)
