"""SQLite task records and versioned schema for the local runtime."""

import json
import os
import sqlite3
import re
import time
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
            if version > 7:
                raise RuntimeError("Database schema is newer than this Orin version")
            if version == 0:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS messages (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        role TEXT NOT NULL, content TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(session_id) REFERENCES sessions(id)
                    );
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        owner TEXT NOT NULL, request TEXT NOT NULL,
                        kind TEXT NOT NULL, status TEXT NOT NULL,
                        result TEXT, error TEXT, idempotency_key TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(owner, idempotency_key),
                        FOREIGN KEY(session_id) REFERENCES sessions(id)
                    );
                    CREATE TABLE IF NOT EXISTS task_steps (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        name TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    CREATE TABLE IF NOT EXISTS executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        capability TEXT NOT NULL, status TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                        name TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                """)
            if version < 2:
                columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
                if "worker_pid" not in columns:
                    db.execute("ALTER TABLE tasks ADD COLUMN worker_pid INTEGER")
                db.execute("PRAGMA user_version=2")
            if version < 3:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS model_health (
                        model TEXT PRIMARY KEY,
                        context_window INTEGER,
                        tool_support INTEGER,
                        json_mode INTEGER,
                        quota_remaining INTEGER,
                        cooldown_until TEXT,
                        healthy INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS usage_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        model TEXT NOT NULL,
                        role TEXT NOT NULL,
                        input_tokens INTEGER,
                        output_tokens INTEGER,
                        latency_ms REAL,
                        success INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    PRAGMA user_version=3;
                """)
            if version < 4:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        path TEXT NOT NULL,
                        byte_count INTEGER NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    PRAGMA user_version=4;
                """)
            if version < 5:
                columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
                if "budget_state" not in columns:
                    db.execute("ALTER TABLE tasks ADD COLUMN budget_state TEXT")
                db.execute("PRAGMA user_version=5")
            if version < 6:
                columns = {row[1] for row in db.execute("PRAGMA table_info(model_health)")}
                if "state" not in columns:
                    db.execute("ALTER TABLE model_health ADD COLUMN state TEXT")
                db.execute("PRAGMA user_version=6")
            if version < 7:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL, category TEXT NOT NULL,
                        content TEXT NOT NULL, provenance TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        expires_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS memories_owner ON memories(owner, category);
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, content);
                    CREATE TABLE IF NOT EXISTS memory_vectors (
                        memory_id TEXT PRIMARY KEY, embedding TEXT NOT NULL,
                        FOREIGN KEY(memory_id) REFERENCES memories(id)
                    );
                    CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memories BEGIN
                        INSERT INTO memory_fts(id, content) VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE OF content ON memories BEGIN
                        DELETE FROM memory_fts WHERE id=old.id;
                        INSERT INTO memory_fts(id, content) VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memories BEGIN
                        DELETE FROM memory_fts WHERE id=old.id;
                        DELETE FROM memory_vectors WHERE memory_id=old.id;
                    END;
                    CREATE TABLE IF NOT EXISTS skill_versions (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
                        version INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                        content TEXT NOT NULL, procedure TEXT NOT NULL,
                        permissions TEXT NOT NULL, source_task TEXT,
                        evaluation TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(owner, name, version)
                    );
                    CREATE TABLE IF NOT EXISTS skill_executions (
                        task_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL,
                        FOREIGN KEY(task_id) REFERENCES tasks(id),
                        FOREIGN KEY(skill_id) REFERENCES skill_versions(id)
                    );
                    CREATE TABLE IF NOT EXISTS user_corrections (
                        id TEXT PRIMARY KEY, owner TEXT NOT NULL, task_id TEXT NOT NULL,
                        content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(task_id) REFERENCES tasks(id)
                    );
                    PRAGMA user_version=7;
                """)

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

    def relevant_messages(self, owner: str, query: str, limit: int = 3) -> list[str]:
        terms = {part for part in re.findall(r"[a-z0-9_]{4,}", query.lower())
                 if part not in {"please", "about", "summarize", "notifications"}}
        if not terms or limit <= 0:
            return []
        with self.connect() as db:
            rows = db.execute("""SELECT messages.content FROM messages
                JOIN sessions ON messages.session_id=sessions.id
                WHERE sessions.owner=? AND messages.role='user'
                ORDER BY messages.rowid DESC LIMIT 100""", (owner,)).fetchall()
        ranked = []
        for index, row in enumerate(rows):
            content = row["content"]
            if content == query:
                continue
            score = len(terms & set(re.findall(r"[a-z0-9_]{4,}", content.lower())))
            if score:
                ranked.append((score, -index, content[:500]))
        ranked.sort(reverse=True)
        return [content for _, _, content in ranked[:limit]]

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

    def record_model_call(self, task_id: str, model: str, role: str,
                          input_tokens: int | None, output_tokens: int | None,
                          latency_ms: float, success: bool):
        with self.connect() as db:
            db.execute("""INSERT INTO usage_records
                (task_id, model, role, input_tokens, output_tokens, latency_ms, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (task_id, model, role, input_tokens, output_tokens, latency_ms, int(success)))

    def record_artifact(self, task_id: str, path: str, byte_count: int):
        with self.connect() as db:
            db.execute("INSERT INTO artifacts(task_id, path, byte_count) VALUES (?, ?, ?)",
                       (task_id, path, byte_count))

    def save_budget_state(self, task_id: str, owner: str, state: dict):
        with self.connect() as db:
            db.execute("UPDATE tasks SET budget_state=? WHERE id=? AND owner=?",
                       (json.dumps(state), task_id, owner))

    def usage_for_task(self, task_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM usage_records WHERE task_id=? ORDER BY id", (task_id,))]

    def upsert_model_health(self, model: str, context_window: int | None = None,
                            tool_support: bool | None = None, json_mode: bool | None = None,
                            quota_remaining: int | None = None, cooldown_until: str | None = None,
                            healthy: bool = True):
        with self.connect() as db:
            db.execute("""INSERT INTO model_health
                (model, context_window, tool_support, json_mode, quota_remaining, cooldown_until, healthy)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    context_window=excluded.context_window,
                    tool_support=excluded.tool_support,
                    json_mode=excluded.json_mode,
                    quota_remaining=excluded.quota_remaining,
                    cooldown_until=excluded.cooldown_until,
                    healthy=excluded.healthy,
                    updated_at=CURRENT_TIMESTAMP""",
                (model, context_window, tool_support, json_mode, quota_remaining,
                 cooldown_until, int(healthy)))

    def model_health(self, model: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM model_health WHERE model=?", (model,)).fetchone()
            return dict(row) if row else None

    def list_model_health(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT model, context_window, tool_support, json_mode, quota_remaining, "
                "cooldown_until, healthy, updated_at FROM model_health ORDER BY model")]

    def save_model_record(self, record: dict):
        with self.connect() as db:
            db.execute("""INSERT INTO model_health
                (model, context_window, tool_support, json_mode, quota_remaining,
                 cooldown_until, healthy, state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    context_window=excluded.context_window,
                    tool_support=excluded.tool_support,
                    json_mode=excluded.json_mode,
                    quota_remaining=excluded.quota_remaining,
                    cooldown_until=excluded.cooldown_until,
                    healthy=excluded.healthy,
                    state=excluded.state,
                    updated_at=CURRENT_TIMESTAMP""",
                (record["name"], record.get("context_window"), record.get("supports_tools"),
                 record.get("supports_json_mode"), record.get("quota_remaining"),
                 str(record.get("cooldown_until", 0)),
                 int(record.get("quota_remaining") != 0 and
                     record.get("cooldown_until", 0) <= time.time()), json.dumps(record)))

    def load_model_records(self) -> list[dict]:
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT state FROM model_health WHERE state IS NOT NULL")]

    def events(self, task_id: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id", (task_id, after))]
