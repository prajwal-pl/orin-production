"""Bounded, owner-scoped metadata sync for Google read capabilities.

Only a completed page traversal updates the cursor and local index. Provider
responses are data; this module never executes content from a provider.
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from orchestration.integrations import authorize_source
from orchestration.db import connect as sqlite_connect, enable_wal


GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE = "https://www.googleapis.com/drive/v3"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SOURCES = frozenset(("gmail", "drive", "calendar"))
MAX_PAGES = 20


@dataclass(frozen=True)
class SyncRecord:
    source: str
    source_id: str
    title: str
    detail: str
    url: str
    occurred_at: str
    content_level: str = "metadata"


@dataclass(frozen=True)
class SyncResult:
    source: str
    account_id: str
    mode: str
    upserted: int
    deleted: int
    cursor: str


def _text(value: object, limit: int = 300) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def _url(value: object) -> str:
    candidate = _text(value, 600)
    parsed = urlparse(candidate)
    return candidate if parsed.scheme == "https" and parsed.hostname else ""


class SyncStore:
    """Separate SQLite index to avoid changing the task/checkpoint schema."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        enable_wal(self.path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sync_cursors (
                    owner TEXT NOT NULL, account_id TEXT NOT NULL, source TEXT NOT NULL,
                    cursor TEXT NOT NULL, synced_at TEXT NOT NULL,
                    PRIMARY KEY(owner, account_id, source)
                );
                CREATE TABLE IF NOT EXISTS sync_records (
                    owner TEXT NOT NULL, account_id TEXT NOT NULL, source TEXT NOT NULL,
                    source_id TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
                    url TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    content_level TEXT NOT NULL CHECK(content_level IN ('metadata', 'content')),
                    indexed_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                    PRIMARY KEY(owner, account_id, source, source_id)
                );
                CREATE INDEX IF NOT EXISTS sync_records_owner ON sync_records(owner, source);
            """)

    def connect(self) -> sqlite3.Connection:
        return sqlite_connect(self.path)

    def cursor(self, owner: str, account_id: str, source: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT cursor FROM sync_cursors WHERE owner=? AND account_id=? AND source=?",
                             (owner, account_id, source)).fetchone()
            return row["cursor"] if row else None

    def records(self, owner: str, *, source: str | None = None, account_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM sync_records WHERE owner=?"
        params: list[str] = [owner]
        if source is not None:
            sql += " AND source=?"
            params.append(source)
        if account_id is not None:
            sql += " AND account_id=?"
            params.append(account_id)
        sql += " ORDER BY indexed_at DESC, source, source_id"
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, params)]

    def apply(self, owner: str, account_id: str, source: str, cursor: str,
              upserts: list[SyncRecord], deletes: set[str], *, full: bool) -> None:
        if not owner or not account_id or source not in SOURCES or not cursor:
            raise ValueError("Owner, account, source, and cursor are required")
        if any(item.source != source or item.content_level != "metadata" for item in upserts):
            raise ValueError("Provider sync may store only metadata from its own source")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if full:
                db.execute("DELETE FROM sync_records WHERE owner=? AND account_id=? AND source=?",
                           (owner, account_id, source))
            for source_id in deletes:
                db.execute("DELETE FROM sync_records WHERE owner=? AND account_id=? AND source=? AND source_id=?",
                           (owner, account_id, source, source_id))
            for item in upserts:
                db.execute("""INSERT INTO sync_records
                    (owner,account_id,source,source_id,title,detail,url,occurred_at,content_level,indexed_at,fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(owner,account_id,source,source_id) DO UPDATE SET
                    title=excluded.title,detail=excluded.detail,url=excluded.url,
                    occurred_at=excluded.occurred_at,content_level=excluded.content_level,
                    indexed_at=excluded.indexed_at,fetched_at=excluded.fetched_at""",
                    (owner, account_id, item.source, item.source_id, item.title, item.detail,
                     item.url, item.occurred_at, item.content_level, now, now))
            db.execute("""INSERT INTO sync_cursors(owner,account_id,source,cursor,synced_at)
                VALUES (?,?,?,?,?) ON CONFLICT(owner,account_id,source) DO UPDATE SET
                cursor=excluded.cursor,synced_at=excluded.synced_at""",
                (owner, account_id, source, cursor, now))


class SyncEngine:
    def __init__(self, store: SyncStore, client: httpx.AsyncClient | None = None,
                 max_pages: int = MAX_PAGES):
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.store = store
        self.client = client
        self.max_pages = max_pages

    async def _get(self, client: httpx.AsyncClient, url: str, token: str,
                   params: dict | list[tuple[str, str]] | None = None) -> dict:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Unexpected provider response")
        return body

    async def _pages(self, client: httpx.AsyncClient, url: str, token: str,
                     params: dict, next_key: str = "nextPageToken") -> list[dict]:
        pages = []
        page_token = None
        for _ in range(self.max_pages):
            query = dict(params)
            if page_token:
                query["pageToken"] = page_token
            body = await self._get(client, url, token, query)
            pages.append(body)
            page_token = body.get(next_key)
            if not page_token:
                return pages
        raise RuntimeError("Sync page budget exceeded; no cursor was advanced")

    async def sync(self, owner: str, source: str, account_id: str, token: str) -> SyncResult:
        if source not in {"gmail", "drive", "calendar"} or not account_id.strip() or not token:
            raise ValueError("A supported source, account identity, and access token are required")
        authorize_source(owner, source)
        if self.client is not None:
            return await self._sync_with_client(self.client, owner, source, account_id, token)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            return await self._sync_with_client(client, owner, source, account_id, token)

    async def _sync_with_client(self, client: httpx.AsyncClient, owner: str, source: str,
                                account_id: str, token: str) -> SyncResult:
        profile = None
        if source == "gmail":
            profile = await self._get(client, f"{GMAIL}/profile", token)
            actual = _text(profile.get("emailAddress"), 320).lower()
            if not actual or actual != account_id.lower():
                raise PermissionError("Google account does not match the requested sync identity")
        elif source == "drive":
            about = await self._get(client, f"{DRIVE}/about", token,
                                    {"fields": "user(emailAddress)"})
            actual = _text((about.get("user") or {}).get("emailAddress"), 320).lower()
            if not actual or actual != account_id.lower():
                raise PermissionError("Google account does not match the requested sync identity")
        old = self.store.cursor(owner, account_id, source)
        if old:
            try:
                if source == "gmail":
                    upserts, deletes, cursor = await self._gmail_incremental(client, token, old)
                elif source == "drive":
                    upserts, deletes, cursor = await self._drive_incremental(client, token, old)
                else:
                    upserts, deletes, cursor = await self._calendar_incremental(client, token, old)
                self.store.apply(owner, account_id, source, cursor, upserts, deletes, full=False)
                return SyncResult(source, account_id, "incremental", len(upserts), len(deletes), cursor)
            except httpx.HTTPStatusError as error:
                expected = 404 if source == "gmail" else 410
                if error.response.status_code != expected:
                    raise
        if source == "gmail":
            upserts, cursor = await self._gmail_full(client, token, profile)
        elif source == "drive":
            upserts, cursor = await self._drive_full(client, token)
        else:
            upserts, cursor = await self._calendar_full(client, token)
        self.store.apply(owner, account_id, source, cursor, upserts, set(), full=True)
        return SyncResult(source, account_id, "full", len(upserts), 0, cursor)

    async def _gmail_message(self, client: httpx.AsyncClient, token: str,
                             message_id: str) -> SyncRecord | None:
        try:
            body = await self._get(client, f"{GMAIL}/messages/{quote(message_id, safe='')}", token,
                                   [("format", "metadata"), ("metadataHeaders", "Subject"),
                                    ("metadataHeaders", "From"), ("metadataHeaders", "Date")])
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return None
            raise
        headers = {str(item.get("name", "")).lower(): _text(item.get("value"))
                   for item in (body.get("payload") or {}).get("headers", [])}
        thread_id = _text(body.get("threadId") or message_id, 100)
        return SyncRecord("gmail", message_id, headers.get("subject") or "(no subject)",
                          headers.get("from", ""),
                          f"https://mail.google.com/mail/u/0/#all/{quote(thread_id, safe='')}",
                          headers.get("date", ""))

    async def _gmail_full(self, client: httpx.AsyncClient, token: str,
                          profile: dict) -> tuple[list[SyncRecord], str]:
        cursor = _text(profile.get("historyId"), 100)
        if not cursor:
            raise ValueError("Gmail profile did not return a history ID")
        pages = await self._pages(client, f"{GMAIL}/messages", token, {"maxResults": "100"})
        ids = {str(item["id"]) for page in pages for item in (page.get("messages") or []) if item.get("id")}
        records = [record for message_id in ids
                   if (record := await self._gmail_message(client, token, message_id)) is not None]
        return records, cursor

    async def _gmail_incremental(self, client: httpx.AsyncClient, token: str,
                                 old: str) -> tuple[list[SyncRecord], set[str], str]:
        pages = await self._pages(client, f"{GMAIL}/history", token,
                                  {"startHistoryId": old, "maxResults": "500"})
        updates: set[str] = set()
        deletes: set[str] = set()
        for page in pages:
            for history in page.get("history") or []:
                for name in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                    updates.update(str(entry["message"]["id"]) for entry in history.get(name) or []
                                   if (entry.get("message") or {}).get("id"))
                deletes.update(str(entry["message"]["id"]) for entry in history.get("messagesDeleted") or []
                               if (entry.get("message") or {}).get("id"))
        updates -= deletes
        records = []
        for message_id in updates:
            record = await self._gmail_message(client, token, message_id)
            if record is None:
                deletes.add(message_id)
            else:
                records.append(record)
        cursor = _text(pages[-1].get("historyId") or old, 100)
        return records, deletes, cursor

    @staticmethod
    def _drive_record(file: dict) -> SyncRecord:
        source_id = _text(file.get("id"), 100)
        return SyncRecord("drive", source_id, _text(file.get("name")) or "Untitled file",
                          _text(file.get("mimeType"), 100),
                          _url(file.get("webViewLink")) or
                          f"https://drive.google.com/open?id={quote(source_id, safe='')}",
                          _text(file.get("modifiedTime"), 100))

    async def _drive_full(self, client: httpx.AsyncClient,
                          token: str) -> tuple[list[SyncRecord], str]:
        start = await self._get(client, f"{DRIVE}/changes/startPageToken", token)
        cursor = _text(start.get("startPageToken"), 200)
        if not cursor:
            raise ValueError("Drive did not return a start page token")
        pages = await self._pages(client, f"{DRIVE}/files", token, {
            "q": "trashed = false", "pageSize": "100",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,trashed)",
        })
        records = [self._drive_record(file) for page in pages for file in (page.get("files") or [])
                   if file.get("id") and not file.get("trashed")]
        return records, cursor

    async def _drive_incremental(self, client: httpx.AsyncClient, token: str,
                                 old: str) -> tuple[list[SyncRecord], set[str], str]:
        pages = await self._pages(client, f"{DRIVE}/changes", token, {
            "pageToken": old, "pageSize": "100", "includeRemoved": "true",
            "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,modifiedTime,webViewLink,trashed))",
        })
        changes: dict[str, SyncRecord | None] = {}
        for page in pages:
            for change in page.get("changes") or []:
                file_id = _text(change.get("fileId"), 100)
                if not file_id:
                    continue
                file = change.get("file") or {}
                changes[file_id] = (None if change.get("removed") or file.get("trashed") or not file
                                    else self._drive_record(file | {"id": file_id}))
        cursor = _text(pages[-1].get("newStartPageToken"), 200)
        if not cursor:
            raise ValueError("Drive change feed ended without a new start page token")
        return [item for item in changes.values() if item is not None], {
            key for key, item in changes.items() if item is None}, cursor

    @staticmethod
    def _calendar_record(event: dict) -> SyncRecord:
        start = event.get("start") or {}
        return SyncRecord("calendar", _text(event.get("id"), 100),
                          _text(event.get("summary")) or "Busy event",
                          _text(event.get("location"), 200), _url(event.get("htmlLink")),
                          _text(start.get("dateTime") or start.get("date") or event.get("updated"), 100))

    async def _calendar_pages(self, client: httpx.AsyncClient, token: str,
                              cursor: str | None = None) -> list[dict]:
        params = {"maxResults": "250", "showDeleted": "true",
                  "fields": "nextPageToken,nextSyncToken,items(id,summary,location,htmlLink,updated,start,status)"}
        if cursor:
            params["syncToken"] = cursor
        return await self._pages(client, CALENDAR, token, params)

    async def _calendar_full(self, client: httpx.AsyncClient,
                             token: str) -> tuple[list[SyncRecord], str]:
        pages = await self._calendar_pages(client, token)
        cursor = _text(pages[-1].get("nextSyncToken"), 300)
        if not cursor:
            raise ValueError("Calendar did not return a sync token")
        records = [self._calendar_record(event) for page in pages for event in (page.get("items") or [])
                   if event.get("id") and event.get("status") != "cancelled"]
        return records, cursor

    async def _calendar_incremental(self, client: httpx.AsyncClient, token: str,
                                    old: str) -> tuple[list[SyncRecord], set[str], str]:
        pages = await self._calendar_pages(client, token, old)
        changes: dict[str, SyncRecord | None] = {}
        for page in pages:
            for event in page.get("items") or []:
                event_id = _text(event.get("id"), 100)
                if event_id:
                    changes[event_id] = (None if event.get("status") == "cancelled"
                                         else self._calendar_record(event))
        cursor = _text(pages[-1].get("nextSyncToken"), 300)
        if not cursor:
            raise ValueError("Calendar page sequence ended without a sync token")
        return [item for item in changes.values() if item is not None], {
            key for key, item in changes.items() if item is None}, cursor
