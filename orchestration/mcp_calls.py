"""Durable, owner-scoped MCP call proposals awaiting explicit confirmation."""

import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from orchestration.db import connect as sqlite_connect, enable_wal


class MCPCallStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        enable_wal(self.path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_pending_calls (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    server_id TEXT NOT NULL, tool TEXT NOT NULL,
                    arguments TEXT NOT NULL, status TEXT NOT NULL,
                    expires_at REAL NOT NULL, claimed_until REAL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS mcp_calls_owner
                    ON mcp_pending_calls(owner, status, created_at DESC);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.path)

    @staticmethod
    def _present(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        item["arguments"] = json.loads(item["arguments"])
        return item

    def create(self, owner: str, server_id: str, tool: str, arguments: dict,
               ttl_seconds: int = 600) -> dict:
        if not owner or not server_id or not tool:
            raise ValueError("Owner, server, and tool are required")
        if not isinstance(arguments, dict) or not 1 <= ttl_seconds <= 86400:
            raise ValueError("MCP call arguments and lifetime are invalid")
        now = time.time()
        call_id = str(uuid4())
        with self.connect() as db:
            db.execute("""INSERT INTO mcp_pending_calls
                (id, owner, server_id, tool, arguments, status,
                 expires_at, claimed_until, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?)""",
                (call_id, owner, server_id, tool,
                 json.dumps(arguments, sort_keys=True), now + ttl_seconds, now, now))
        return self.get(owner, call_id)

    def get(self, owner: str, call_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM mcp_pending_calls WHERE id=? AND owner=?",
                (call_id, owner)).fetchone()
        return self._present(row)

    def list_pending(self, owner: str) -> list[dict]:
        now = time.time()
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM mcp_pending_calls
                WHERE owner=? AND status='pending' AND expires_at>?
                ORDER BY created_at DESC""", (owner, now)).fetchall()
        return [self._present(row) for row in rows]

    def claim(self, owner: str, call_id: str) -> dict | None:
        now = time.time()
        with self.connect() as db:
            changed = db.execute("""UPDATE mcp_pending_calls
                SET status='executing', claimed_until=?, updated_at=?
                WHERE id=? AND owner=? AND status='pending' AND expires_at>?""",
                (now + 60, now, call_id, owner, now)).rowcount
            row = db.execute(
                "SELECT * FROM mcp_pending_calls WHERE id=? AND owner=?",
                (call_id, owner)).fetchone()
        return self._present(row) if changed else None

    def finish(self, owner: str, call_id: str, status: str) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("Invalid MCP call result")
        now = time.time()
        with self.connect() as db:
            db.execute("""UPDATE mcp_pending_calls
                SET status=?, claimed_until=NULL, updated_at=?
                WHERE id=? AND owner=? AND status='executing'""",
                (status, now, call_id, owner))

    def deny(self, owner: str, call_id: str) -> bool:
        now = time.time()
        with self.connect() as db:
            changed = db.execute("""UPDATE mcp_pending_calls
                SET status='denied', updated_at=?
                WHERE id=? AND owner=? AND status='pending'""",
                (now, call_id, owner)).rowcount
        return bool(changed)
