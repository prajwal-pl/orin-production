"""Small SQLite helpers shared by Orin's local stores.

WAL lets the Telegram bot, API server, CLI, and schedule worker read while
another process writes. SQLite keeps the journal mode on the database file, so
enabling it at store construction is enough for later connections.
"""

import sqlite3
from pathlib import Path


def connect(path: Path, *, foreign_keys: bool = False) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys=ON")
    return connection


def enable_wal(path: Path) -> None:
    """Best-effort WAL switch; unsupported filesystems keep the default journal."""
    try:
        db = sqlite3.connect(path, timeout=30)
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA journal_mode=WAL")
        finally:
            db.close()
    except sqlite3.Error:
        # The store still works with the rollback journal. Never fail startup
        # because a local filesystem does not support shared-memory WAL files.
        pass
