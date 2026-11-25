"""Owner-scoped search over provider metadata and explicitly approved local text."""

import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from orchestration.sync import SyncStore
from orchestration.local_tools import _open_beneath


_WORDS = re.compile(r"[\w]+", re.UNICODE)
_LOCAL_SUFFIXES = frozenset((".md", ".txt"))
MAX_LOCAL_BYTES = 32768


@dataclass(frozen=True)
class SearchHit:
    source: str
    account_id: str
    source_id: str
    title: str
    detail: str
    citation: str
    occurred_at: str
    fetched_at: str
    content_kind: str
    score: int


class SearchIndex:
    def __init__(self, store: SyncStore):
        self.store = store

    def ingest_evidence(self, owner: str, items: list[dict]) -> int:
        """Ingest declared evidence; no provider body is inferred or fetched."""
        if not owner:
            raise ValueError("An owner is required")
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for item in items:
            source = str(item.get("source") or "").strip()
            account_id = str(item.get("account_id") or item.get("account") or "").strip()
            source_id = str(item.get("source_id") or "").strip()
            kind = str(item.get("content_kind") or "metadata")
            if not source or not account_id or not source_id or kind not in {"metadata", "content"}:
                raise ValueError("Evidence requires source, account_id, source_id, and content_kind")
            if source in {"gmail", "drive", "calendar"} and kind != "metadata":
                raise ValueError("Google metadata grants do not allow content indexing")
            citation = str(item.get("url") or "")[:600]
            parsed = urlparse(citation)
            if citation and (parsed.scheme != "https" or not parsed.hostname):
                raise ValueError("Provider evidence must cite an HTTPS source")
            title = str(item.get("title") or "")[:500]
            detail = str(item.get("detail") or "")[:MAX_LOCAL_BYTES]
            occurred_at = str(item.get("occurred_at") or "")[:100]
            fetched_at = str(item.get("fetched_at") or item.get("observed_at") or now)[:100]
            rows.append((owner, account_id, source, source_id, title, detail, citation,
                         occurred_at, kind, now, fetched_at))
        with self.store.connect() as db:
            db.executemany("""INSERT INTO sync_records
                (owner,account_id,source,source_id,title,detail,url,occurred_at,content_level,indexed_at,fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(owner,account_id,source,source_id) DO UPDATE SET
                title=excluded.title,detail=excluded.detail,url=excluded.url,
                occurred_at=excluded.occurred_at,content_level=excluded.content_level,
                indexed_at=excluded.indexed_at,fetched_at=excluded.fetched_at""", rows)
        return len(rows)

    def index_local_files(self, owner: str, approved_root: Path,
                          relative_paths: list[str]) -> int:
        """Read only named text files below a caller-approved root."""
        if not owner or not relative_paths:
            raise ValueError("Owner and explicit relative paths are required")
        root = Path(approved_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Approved root must be a directory")
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for relative in relative_paths:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() not in _LOCAL_SUFFIXES:
                raise PermissionError("Local index path is outside the approved text scope")
            # Open each component without following symlinks. The descriptor is
            # the file we inspect and read, even if a path changes concurrently.
            try:
                descriptor = _open_beneath(root, candidate, os.O_RDONLY)
            except OSError as error:
                raise PermissionError("Local index path is unavailable or outside the approved root") from error
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise PermissionError("Local index target must be a regular file")
                if info.st_size > MAX_LOCAL_BYTES:
                    raise ValueError("Local text file exceeds the indexing size limit")
                raw = stream.read(MAX_LOCAL_BYTES + 1)
            if len(raw) > MAX_LOCAL_BYTES:
                raise ValueError("Local text file exceeds the indexing size limit")
            content = raw.decode("utf-8")
            path = root / candidate
            rows.append((owner, str(root), "filesystem", str(path), path.name, content,
                         path.as_uri(), datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                         "content", now, now))
        with self.store.connect() as db:
            db.executemany("""INSERT INTO sync_records
                (owner,account_id,source,source_id,title,detail,url,occurred_at,content_level,indexed_at,fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(owner,account_id,source,source_id) DO UPDATE SET
                title=excluded.title,detail=excluded.detail,url=excluded.url,
                occurred_at=excluded.occurred_at,content_level=excluded.content_level,
                indexed_at=excluded.indexed_at,fetched_at=excluded.fetched_at""", rows)
        return len(rows)

    def search(self, owner: str, query: str, *, include_content: bool = False,
               account_id: str | None = None, sources: set[str] | None = None,
               limit: int = 10) -> list[SearchHit]:
        if not owner or not query.strip() or not 1 <= limit <= 100:
            raise ValueError("Owner, query, and a limit from 1 to 100 are required")
        terms = {term.casefold() for term in _WORDS.findall(query) if len(term) >= 2}
        if not terms:
            return []
        rows = self.store.records(owner, account_id=account_id)
        hits = []
        for row in rows:
            if sources is not None and row["source"] not in sources:
                continue
            if row["content_level"] == "content" and not include_content:
                continue
            title = row["title"].casefold()
            detail = row["detail"].casefold()
            matched = {term for term in terms if term in title or term in detail}
            if not matched:
                continue
            score = sum(3 if term in title else 1 for term in matched)
            hits.append(SearchHit(row["source"], row["account_id"], row["source_id"],
                                  row["title"], row["detail"][:500], row["url"],
                                  row["occurred_at"], row["fetched_at"],
                                  row["content_level"], score))
        hits.sort(key=lambda item: (-item.score, item.source, item.source_id))
        return hits[:limit]
