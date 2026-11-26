"""Owner-scoped capability grants, exact approvals, and local tool audit."""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from orchestration.db import connect as sqlite_connect, enable_wal


class PolicyDenied(PermissionError):
    """A capability grant or approval did not authorize this action."""


def _parameters(parameters: dict | None) -> tuple[str, str]:
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, dict):
        raise ValueError("Action parameters must be a JSON object")
    raw = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


class PolicyStore:
    """A separate SQLite database keeps policy changes independent of task migrations."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        enable_wal(self.path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS capability_grants (
                    owner TEXT NOT NULL, capability TEXT NOT NULL, operation TEXT NOT NULL,
                    PRIMARY KEY(owner, capability, operation)
                );
                CREATE TABLE IF NOT EXISTS filesystem_roots (
                    owner TEXT NOT NULL, path TEXT NOT NULL, operation TEXT NOT NULL,
                    PRIMARY KEY(owner, path, operation)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, capability TEXT NOT NULL,
                    parameters TEXT NOT NULL, parameters_hash TEXT NOT NULL,
                    status TEXT NOT NULL, expires_at REAL NOT NULL,
                    created_at REAL NOT NULL, consumed_at REAL
                );
                CREATE TABLE IF NOT EXISTS tool_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    capability TEXT NOT NULL, operation TEXT NOT NULL,
                    status TEXT NOT NULL, details TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS approvals_owner ON approvals(owner, created_at DESC);
                CREATE INDEX IF NOT EXISTS audit_owner ON tool_audit(owner, created_at DESC);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.path)

    @staticmethod
    def _operation(operation: str) -> None:
        if operation not in ("read", "write"):
            raise ValueError("Operation must be read or write")

    def grant(self, owner: str, capability: str, operation: str) -> None:
        self._operation(operation)
        if not owner or not capability:
            raise ValueError("Owner and capability are required")
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO capability_grants VALUES (?, ?, ?)",
                       (owner, capability, operation))

    def revoke(self, owner: str, capability: str, operation: str) -> bool:
        self._operation(operation)
        with self.connect() as db:
            changed = db.execute(
                "DELETE FROM capability_grants WHERE owner=? AND capability=? AND operation=?",
                (owner, capability, operation)).rowcount
        if changed:
            self.audit(owner, capability, operation, "revoked")
        return bool(changed)

    def list_grants(self, owner: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT capability, operation FROM capability_grants
                WHERE owner=? ORDER BY capability, operation""", (owner,)).fetchall()
        return [dict(row) for row in rows]

    def has_grant(self, owner: str, capability: str, operation: str) -> bool:
        self._operation(operation)
        with self.connect() as db:
            return db.execute("SELECT 1 FROM capability_grants WHERE owner=? AND capability=? AND operation=?",
                              (owner, capability, operation)).fetchone() is not None

    def grant_root(self, owner: str, path: Path, operation: str = "read") -> Path:
        self._operation(operation)
        root = Path(path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Approved filesystem root must be a directory")
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO filesystem_roots VALUES (?, ?, ?)",
                       (owner, str(root), operation))
        self.grant(owner, "filesystem", operation)
        return root

    def roots(self, owner: str, operation: str) -> list[Path]:
        self._operation(operation)
        with self.connect() as db:
            rows = db.execute("SELECT path FROM filesystem_roots WHERE owner=? AND operation=?",
                              (owner, operation)).fetchall()
        return [Path(row["path"]) for row in rows]

    def list_roots(self, owner: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT path, operation FROM filesystem_roots
                WHERE owner=? ORDER BY path, operation""", (owner,)).fetchall()
        return [dict(row) for row in rows]

    def revoke_root(self, owner: str, path: Path, operation: str = "read") -> bool:
        self._operation(operation)
        # Grants store the resolved path. Resolve again when possible, but do
        # not require the directory to still exist so a deleted root can be
        # removed from policy.
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            resolved = Path(os.path.abspath(os.path.normpath(str(candidate))))
        with self.connect() as db:
            changed = db.execute(
                """DELETE FROM filesystem_roots
                WHERE owner=? AND path=? AND operation=?""",
                (owner, str(resolved), operation)).rowcount
        if changed:
            self.audit(owner, "filesystem", operation, "root_revoked", str(resolved))
        return bool(changed)

    def request_approval(self, owner: str, capability: str, parameters: dict,
                         ttl_seconds: int = 600) -> dict:
        if not self.has_grant(owner, capability, "write"):
            raise PolicyDenied("Write capability is not granted")
        if not 1 <= ttl_seconds <= 86400:
            raise ValueError("Approval lifetime must be between 1 second and 1 day")
        raw, digest = _parameters(parameters)
        now = time.time()
        approval_id = str(uuid4())
        with self.connect() as db:
            db.execute("""INSERT INTO approvals
                (id, owner, capability, parameters, parameters_hash, status, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (approval_id, owner, capability, raw, digest, now + ttl_seconds, now))
        self.audit(owner, capability, "write", "approval_requested", approval_id)
        return self.get_approval(owner, approval_id)

    def get_approval(self, owner: str, approval_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id=? AND owner=?",
                             (approval_id, owner)).fetchone()
        return self._present(row) if row else None

    @staticmethod
    def _present(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["parameters"] = json.loads(result["parameters"])
        return result

    def list_approvals(self, owner: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM approvals WHERE owner=? ORDER BY created_at DESC",
                              (owner,)).fetchall()
        return [self._present(row) for row in rows]

    def approve(self, owner: str, approval_id: str) -> dict:
        now = time.time()
        with self.connect() as db:
            changed = db.execute("""UPDATE approvals SET status='approved'
                WHERE id=? AND owner=? AND status='pending' AND expires_at>?""",
                (approval_id, owner, now)).rowcount
        if not changed:
            raise PolicyDenied("Approval is unavailable or expired")
        approval = self.get_approval(owner, approval_id)
        self.audit(owner, approval["capability"], "write", "approval_approved", approval_id)
        return approval

    def deny(self, owner: str, approval_id: str) -> dict:
        with self.connect() as db:
            changed = db.execute("""UPDATE approvals SET status='denied'
                WHERE id=? AND owner=? AND status IN ('pending', 'approved')""",
                (approval_id, owner)).rowcount
        if not changed:
            raise PolicyDenied("Approval is unavailable")
        approval = self.get_approval(owner, approval_id)
        self.audit(owner, approval["capability"], "write", "approval_denied", approval_id)
        return approval

    def authorize(self, owner: str, capability: str, operation: str,
                  parameters: dict | None = None, approval_id: str | None = None) -> None:
        self._operation(operation)
        if not self.has_grant(owner, capability, operation):
            self.audit(owner, capability, operation, "denied", "missing grant")
            raise PolicyDenied("Capability is not granted")
        if operation == "write":
            if not approval_id:
                self.audit(owner, capability, operation, "denied", "missing approval")
                raise PolicyDenied("Exact action approval is required")
            _, digest = _parameters(parameters)
            now = time.time()
            with self.connect() as db:
                changed = db.execute("""UPDATE approvals
                    SET status='consumed', consumed_at=?
                    WHERE id=? AND owner=? AND capability=? AND parameters_hash=?
                    AND status='approved' AND expires_at>?""",
                    (now, approval_id, owner, capability, digest, now)).rowcount
            if not changed:
                self.audit(owner, capability, operation, "denied", "approval mismatch, replay, or expiry")
                raise PolicyDenied("Approval does not match this action or is no longer valid")
        self.audit(owner, capability, operation, "authorized",
                   approval_id if operation == "write" else "")

    def audit(self, owner: str, capability: str, operation: str, status: str,
              details: str = "") -> None:
        # Callers supply status codes, never raw external content or credentials.
        with self.connect() as db:
            db.execute("INSERT INTO tool_audit(owner,capability,operation,status,details,created_at) "
                       "VALUES(?,?,?,?,?,?)", (owner, capability, operation, status, details, time.time()))

    def audit_for_owner(self, owner: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM tool_audit WHERE owner=? ORDER BY id", (owner,)).fetchall()
        return [dict(row) for row in rows]
