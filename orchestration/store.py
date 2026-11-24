"""SQLite task records and versioned schema for the local runtime."""

import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4


def database_path() -> Path:
    return Path(os.getenv("ORIN_DATABASE_PATH", "~/.orion/database/orin.db")).expanduser()


class TaskStore:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        self.migrate()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def migrate(self):
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError("Database schema is newer than this Orin version")
            if version == 0:
                db.executescript("""
                    CREATE TABLE sessions (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE messages (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        role TEXT NOT NULL, content TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(session_id) REFERENCES sessions(id)
                    );
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        owner TEXT NOT NULL, request TEXT NOT NULL,
                        kind TEXT NOT NULL, status TEXT NOT NULL,
                        result TEXT, error TEXT, idempotency_key TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(owner, idempotency_key),
                        FOREIGN KEY(session_id) REFERENCES sessions(id)
                    );
                    CREATE TABLE task_steps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        name TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    CREATE TABLE executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        capability TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    CREATE TABLE events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                """)
            if version < 2:
                db.execute("ALTER TABLE tasks ADD COLUMN worker_pid INTEGER")
                db.execute("PRAGMA user_version=2")

    def create_task(self, owner: str, session_id: str, request: str, kind: str,
                    idempotency_key: str | None = None) -> dict:
        task_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO sessions(id, owner) VALUES (?, ?)", (session_id, owner))
            session = db.execute("SELECT owner FROM sessions WHERE id=?", (session_id,)).fetchone()
            if session["owner"] != owner:
                raise PermissionError("Session belongs to another user")
            db.execute("""INSERT OR IGNORE INTO tasks
                (id, session_id, owner, request, kind, status, idempotency_key)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (task_id, session_id, owner, request, kind, idempotency_key))
            row = db.execute("SELECT * FROM tasks WHERE owner=? AND idempotency_key=?",
                             (owner, idempotency_key)).fetchone() if idempotency_key else db.execute(
                                 "SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row["id"] == task_id:
                db.execute("INSERT INTO messages(id, session_id, role, content) VALUES (?, ?, 'user', ?)",
                           (str(uuid4()), session_id, request))
                db.execute("INSERT INTO events(task_id, name) VALUES (?, 'created')", (task_id,))
        return dict(row)

    def get_task(self, task_id: str, owner: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
            return dict(row) if row else None

    def list_tasks(self, owner: str, session_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if session_id:
                rows = db.execute("SELECT * FROM tasks WHERE owner=? AND session_id=? ORDER BY created_at DESC", (owner, session_id))
            else:
                rows = db.execute("SELECT * FROM tasks WHERE owner=? ORDER BY created_at DESC", (owner,))
            return [dict(row) for row in rows]

    def list_sessions(self, owner: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM sessions WHERE owner=? ORDER BY created_at DESC", (owner,))]

    def messages(self, owner: str, session_id: str) -> list[dict] | None:
        with self.connect() as db:
            session = db.execute("SELECT id FROM sessions WHERE id=? AND owner=?",
                                 (session_id, owner)).fetchone()
            if session is None:
                return None
            return [dict(row) for row in db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid", (session_id,))]

    def transition(self, task_id: str, owner: str, from_status: tuple[str, ...], to_status: str,
                   result: str | None = None, error: str | None = None) -> bool:
        placeholders = ",".join("?" for _ in from_status)
        with self.connect() as db:
            worker_pid = os.getpid() if to_status == "running" else None
            cursor = db.execute(f"""UPDATE tasks SET status=?, result=COALESCE(?, result), error=?, worker_pid=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner=? AND status IN ({placeholders})""",
                (to_status, result, error, worker_pid, task_id, owner, *from_status))
            if cursor.rowcount:
                db.execute("INSERT INTO events(task_id, name) VALUES (?, ?)", (task_id, to_status))
                if to_status == "completed" and result:
                    session_id = db.execute("SELECT session_id FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
                    db.execute("INSERT INTO messages(id, session_id, role, content) VALUES (?, ?, 'assistant', ?)",
                               (str(uuid4()), session_id, result))
            return bool(cursor.rowcount)

    def record_step(self, task_id: str, name: str, status: str):
        with self.connect() as db:
            db.execute("INSERT INTO task_steps(task_id, name, status) VALUES (?, ?, ?)", (task_id, name, status))
            db.execute("INSERT INTO events(task_id, name, data) VALUES (?, 'step', ?)",
                       (task_id, json.dumps({"name": name, "status": status})))

    def record_execution(self, task_id: str, capability: str, status: str):
        with self.connect() as db:
            db.execute("INSERT INTO executions(task_id, capability, status) VALUES (?, ?, ?)",
                       (task_id, capability, status))

    def events(self, task_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id", (task_id, after))]
