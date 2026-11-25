"""Durable, explicitly approved external writes with safe ambiguous recovery."""

import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx

from orchestration.google_oauth import has_refresh_token, refreshed_access_token
from orchestration.google_writes import (WRITE_SOURCES, execute_google_write,
                                         reconcile_google_write, validate_write)
from orchestration.policy import PolicyStore
from orchestration.integrations import MissingCredential


class ActionStore:
    def __init__(self, path: Path, policy: PolicyStore):
        self.path = Path(path)
        self.policy = policy
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, capability TEXT NOT NULL,
                    parameters TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    approval_id TEXT NOT NULL, status TEXT NOT NULL,
                    provider_id TEXT, error_type TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(owner, capability, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS actions_owner ON actions(owner,created_at DESC);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @staticmethod
    def _present(row):
        if row is None:
            return None
        item = dict(row)
        item["parameters"] = json.loads(item["parameters"])
        return item

    def get(self, owner: str, action_id: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM actions WHERE id=? AND owner=?", (action_id, owner)).fetchone()
        return self._present(row)

    def list(self, owner: str):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM actions WHERE owner=? ORDER BY created_at DESC", (owner,)).fetchall()
        return [self._present(row) for row in rows]

    def prepare(self, owner: str, capability: str, parameters: dict,
                idempotency_key: str, ttl_seconds: int = 600):
        normalized = validate_write(capability, parameters)
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("A bounded idempotency key is required")
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.connect() as db:
            old = db.execute("SELECT * FROM actions WHERE owner=? AND capability=? AND idempotency_key=?",
                             (owner, capability, idempotency_key)).fetchone()
        if old:
            if old["parameters"] != raw:
                raise ValueError("Idempotency key already belongs to different parameters")
            return self._present(old)
        approval = self.policy.request_approval(owner, capability, normalized, ttl_seconds)
        action_id = str(uuid4())
        with self.connect() as db:
            try:
                db.execute("""INSERT INTO actions
                    (id,owner,capability,parameters,idempotency_key,approval_id,status)
                    VALUES (?,?,?,?,?,?,'prepared')""",
                    (action_id, owner, capability, raw, idempotency_key, approval["id"]))
            except sqlite3.IntegrityError:
                row = db.execute("SELECT * FROM actions WHERE owner=? AND capability=? AND idempotency_key=?",
                                 (owner, capability, idempotency_key)).fetchone()
                if row["parameters"] != raw:
                    raise ValueError("Idempotency key already belongs to different parameters") from None
                return self._present(row)
        self.policy.audit(owner, capability, "write", "prepared", "approval required")
        return self.get(owner, action_id)

    def _set_status(self, owner: str, action_id: str, expected: str,
                    status: str, provider_id: str = "", error_type: str = "") -> bool:
        with self.connect() as db:
            changed = db.execute("""UPDATE actions SET status=?,provider_id=?,error_type=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner=? AND status=?""",
                (status, provider_id, error_type, action_id, owner, expected)).rowcount
        return bool(changed)

    async def execute(self, owner: str, action_id: str, client=None):
        action = self.get(owner, action_id)
        if not action:
            raise KeyError("Action not found")
        if action["status"] != "prepared":
            return action
        source = WRITE_SOURCES[action["capability"]]
        if not has_refresh_token(owner, source):
            raise MissingCredential("Write credential is not connected")
        token = await refreshed_access_token(owner, source)
        if not self._set_status(owner, action_id, "prepared", "executing"):
            return self.get(owner, action_id)
        try:
            self.policy.authorize(owner, action["capability"], "write",
                                  action["parameters"], action["approval_id"])
        except Exception:
            self._set_status(owner, action_id, "executing", "denied")
            raise
        try:
            outcome = await execute_google_write(action["capability"], action["parameters"], token,
                                                 owner, action["idempotency_key"], client)
        except Exception as error:
            # A timeout after provider commit is ambiguous. Never auto-retry.
            definite_rejection = (isinstance(error, httpx.HTTPStatusError) and
                                  error.response.status_code in range(400, 500) and
                                  error.response.status_code not in {408, 409, 429})
            status = "failed" if definite_rejection else "unknown"
            self._set_status(owner, action_id, "executing", status, error_type=type(error).__name__)
            self.policy.audit(owner, action["capability"], "write", status, type(error).__name__)
            return self.get(owner, action_id)
        self._set_status(owner, action_id, "executing", "completed", outcome.get("provider_id", ""))
        self.policy.audit(owner, action["capability"], "write", "completed", "")
        return self.get(owner, action_id)

    async def reconcile(self, owner: str, action_id: str, client=None):
        action = self.get(owner, action_id)
        if not action:
            raise KeyError("Action not found")
        if action["status"] not in {"unknown", "executing"}:
            return action
        source = WRITE_SOURCES[action["capability"]]
        if not has_refresh_token(owner, source):
            raise RuntimeError("Write credential is not connected")
        token = await refreshed_access_token(owner, source)
        outcome = await reconcile_google_write(action["capability"], token, owner,
                                               action["idempotency_key"], action["parameters"], client)
        if outcome:
            self._set_status(owner, action_id, action["status"], "completed", outcome["provider_id"])
            self.policy.audit(owner, action["capability"], "read", "reconciled", "")
        return self.get(owner, action_id)
