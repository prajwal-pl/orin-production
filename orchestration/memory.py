"""Owner-scoped, inspectable memory with FTS and a rebuildable local vector cache."""

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from orchestration.store import TaskStore

CATEGORIES = frozenset({"episodic", "semantic", "procedural", "preference", "working"})
RETENTION_DAYS = {"episodic": 30, "semantic": None, "procedural": None,
                  "preference": None, "working": 7}
DIMENSIONS = 128


def embedding(text: str) -> list[float]:
    """Deterministic character n-grams; useful for fuzzy recall, not an LLM embedding."""
    normalized = " ".join(re.findall(r"[a-z0-9]+", text.casefold()))
    vector = [0.0] * DIMENSIONS
    for index in range(max(0, len(normalized) - 2)):
        gram = normalized[index:index + 3]
        slot = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=4).digest(), "big") % DIMENSIONS
        vector[slot] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector] if magnitude else vector


class MemoryStore:
    def __init__(self, store: TaskStore):
        self.store = store

    def prune(self) -> int:
        with self.store.connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at<=?",
                                (datetime.now(timezone.utc).isoformat(),))
            return cursor.rowcount

    def add(self, owner: str, category: str, content: str, provenance: str) -> dict:
        if category not in CATEGORIES or not content.strip() or not provenance.strip():
            raise ValueError("A valid category, content, and provenance are required")
        if len(content) > 8000:
            raise ValueError("Memory content exceeds 8000 characters")
        days = RETENTION_DAYS[category]
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else None
        memory_id = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO memories(id, owner, category, content, provenance, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                       (memory_id, owner, category, content.strip(), provenance, expires))
            db.execute("INSERT INTO memory_vectors(memory_id, embedding) VALUES (?, ?)",
                       (memory_id, json.dumps(embedding(content))))
        return self.get(owner, memory_id)

    def get(self, owner: str, memory_id: str) -> dict | None:
        self.prune()
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM memories WHERE owner=? AND id=? AND (expires_at IS NULL OR expires_at>?)",
                             (owner, memory_id, datetime.now(timezone.utc).isoformat())).fetchone()
        return dict(row) if row else None

    def list(self, owner: str) -> list[dict]:
        self.prune()
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM memories WHERE owner=? AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at DESC, rowid DESC",
                              (owner, datetime.now(timezone.utc).isoformat())).fetchall()
        return [dict(row) for row in rows]

    def correct(self, owner: str, memory_id: str, content: str) -> dict:
        self.prune()
        if not content.strip() or len(content) > 8000:
            raise ValueError("Memory content must be 1 to 8000 characters")
        with self.store.connect() as db:
            cursor = db.execute("UPDATE memories SET content=?, provenance=provenance || '; user correction' WHERE id=? AND owner=?",
                                (content.strip(), memory_id, owner))
            if not cursor.rowcount:
                raise KeyError("Memory not found")
            db.execute("INSERT OR REPLACE INTO memory_vectors(memory_id, embedding) VALUES (?, ?)",
                       (memory_id, json.dumps(embedding(content))))
        return self.get(owner, memory_id)

    def delete(self, owner: str, memory_id: str) -> None:
        with self.store.connect() as db:
            cursor = db.execute("DELETE FROM memories WHERE id=? AND owner=?", (memory_id, owner))
            if not cursor.rowcount:
                raise KeyError("Memory not found")

    def export(self, owner: str) -> list[dict]:
        return self.list(owner)

    def rebuild_index(self) -> None:
        with self.store.connect() as db:
            db.execute("DELETE FROM memory_fts")
            db.execute("DELETE FROM memory_vectors")
            for row in db.execute("SELECT id, content FROM memories").fetchall():
                db.execute("INSERT INTO memory_fts(id, content) VALUES (?, ?)", (row["id"], row["content"]))
                db.execute("INSERT INTO memory_vectors(memory_id, embedding) VALUES (?, ?)",
                           (row["id"], json.dumps(embedding(row["content"]))))

    def search(self, owner: str, query: str, limit: int = 5) -> list[dict]:
        if not query.strip() or limit <= 0:
            return []
        self.prune()
        query_vector = embedding(query)
        terms = re.findall(r"[a-z0-9]+", query.casefold())
        fts_ids: set[str] = set()
        with self.store.connect() as db:
            if terms:
                expression = " OR ".join(f'"{term}"' for term in set(terms))
                fts_ids = {row[0] for row in db.execute("SELECT id FROM memory_fts WHERE memory_fts MATCH ?", (expression,))}
            rows = db.execute("""SELECT m.*, v.embedding FROM memories m
                JOIN memory_vectors v ON v.memory_id=m.id
                WHERE m.owner=? AND (m.expires_at IS NULL OR m.expires_at>?)""",
                (owner, datetime.now(timezone.utc).isoformat())).fetchall()
        ranked = []
        for row in rows:
            similarity = sum(a * b for a, b in zip(query_vector, json.loads(row["embedding"])))
            score = similarity + (0.5 if row["id"] in fts_ids else 0)
            if score > 0.1:
                ranked.append((score, row["created_at"], {key: row[key] for key in row.keys() if key != "embedding"}))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [entry[2] for entry in ranked[:limit]]
