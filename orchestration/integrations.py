"""Read-only source adapters and an integration-neutral evidence contract."""

import asyncio
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from urllib.parse import quote, urlparse

import httpx

from orchestration.google_oauth import has_refresh_token, refreshed_access_token


@dataclass(frozen=True)
class Evidence:
    source: str
    source_id: str
    title: str
    detail: str
    url: str
    occurred_at: str = ""


@dataclass(frozen=True)
class SourceSpec:
    key: str
    capability: str
    token_env: str
    owner_env: str
    oauth_scope: str
    description: str
    read_only: bool = True


SOURCES = {
    "gmail": SourceSpec("gmail", "gmail.inbox.read", "ORIN_GMAIL_ACCESS_TOKEN",
                        "ORIN_GMAIL_ALLOWED_USERS", "https://www.googleapis.com/auth/gmail.metadata",
                        "Unread inbox headers; no message bodies"),
    "drive": SourceSpec("drive", "drive.files.metadata.read", "ORIN_DRIVE_ACCESS_TOKEN",
                        "ORIN_DRIVE_ALLOWED_USERS", "https://www.googleapis.com/auth/drive.metadata.readonly",
                        "Recent file metadata; no file contents"),
    "calendar": SourceSpec("calendar", "calendar.events.read", "ORIN_CALENDAR_ACCESS_TOKEN",
                           "ORIN_CALENDAR_ALLOWED_USERS", "https://www.googleapis.com/auth/calendar.events.readonly",
                           "Upcoming calendar event metadata"),
    "github": SourceSpec("github", "github.notifications.read", "GITHUB_TOKEN",
                         "ORIN_GITHUB_ALLOWED_USERS", "notifications",
                         "Unread GitHub notifications"),
}


class MissingCredential(RuntimeError):
    """The owner has permission to use a source but has not connected it."""


def connected_sources(owner: str) -> list[str]:
    return [key for key, source in SOURCES.items()
            if owner in allowed_users(source) and
            (os.getenv(source.token_env, "").strip() or
             (key != "github" and has_refresh_token(owner, key)))]


def allowed_users(source: SourceSpec) -> set[str]:
    default = "local" if source.key == "github" else ""
    return {part.strip() for part in os.getenv(source.owner_env, default).split(",") if part.strip()}


def authorize_source(owner: str, key: str) -> None:
    if owner not in allowed_users(SOURCES[key]):
        raise PermissionError(f"{key} read access is not enabled for this user")


def _safe(value: object, limit: int = 300) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ")[:limit]


def _https_url(value: object) -> str:
    candidate = _safe(value, 500)
    parsed = urlparse(candidate)
    return candidate if parsed.scheme == "https" and parsed.hostname else ""


async def _request_json(client: httpx.AsyncClient, url: str, token: str,
                        params: dict | list[tuple[str, str]] | None = None) -> dict:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Unexpected integration response")
    return body


async def fetch_gmail(token: str, client: httpx.AsyncClient | None = None) -> list[Evidence]:
    async def work(http: httpx.AsyncClient) -> list[Evidence]:
        body = await _request_json(http, "https://gmail.googleapis.com/gmail/v1/users/me/messages", token,
                                   [("labelIds", "INBOX"), ("labelIds", "UNREAD"), ("maxResults", "10")])
        messages = body.get("messages") or []
        if not isinstance(messages, list):
            raise ValueError("Unexpected Gmail message list")
        items = []
        for message in messages[:10]:
            message_id = _safe(message.get("id"), 100)
            if not message_id:
                continue
            metadata = await _request_json(
                http, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id, safe='')}",
                token, [("format", "metadata"), ("metadataHeaders", "Subject"),
                        ("metadataHeaders", "From"), ("metadataHeaders", "Date")],
            )
            headers = {str(header.get("name", "")).lower(): _safe(header.get("value"))
                       for header in (metadata.get("payload") or {}).get("headers", [])}
            thread_id = _safe(message.get("threadId") or metadata.get("threadId") or message_id, 100)
            items.append(Evidence("gmail", message_id, headers.get("subject") or "(no subject)",
                                  headers.get("from", ""),
                                  f"https://mail.google.com/mail/u/0/#inbox/{quote(thread_id, safe='')}",
                                  headers.get("date", "")))
        return items
    if client is not None:
        async with asyncio.timeout(20):
            return await work(client)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        async with asyncio.timeout(20):
            return await work(http)


async def fetch_drive(token: str, client: httpx.AsyncClient | None = None) -> list[Evidence]:
    async def work(http: httpx.AsyncClient) -> list[Evidence]:
        body = await _request_json(http, "https://www.googleapis.com/drive/v3/files", token, {
            "q": "trashed = false", "orderBy": "modifiedTime desc", "pageSize": "10",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)",
        })
        files = body.get("files") or []
        if not isinstance(files, list):
            raise ValueError("Unexpected Drive file list")
        return [Evidence("drive", _safe(file.get("id"), 100), _safe(file.get("name")) or "Untitled file",
                         _safe(file.get("mimeType"), 100),
                         _https_url(file.get("webViewLink")) or
                         f"https://drive.google.com/open?id={quote(_safe(file.get('id'), 100), safe='')}",
                         _safe(file.get("modifiedTime"), 100))
                for file in files[:10] if file.get("id")]
    if client is not None:
        return await work(client)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        return await work(http)


async def fetch_calendar(token: str, client: httpx.AsyncClient | None = None,
                         now: datetime | None = None) -> list[Evidence]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Calendar window requires a timezone-aware timestamp")
    async def work(http: httpx.AsyncClient) -> list[Evidence]:
        body = await _request_json(http,
            "https://www.googleapis.com/calendar/v3/calendars/primary/events", token, {
                "timeMin": now.isoformat(), "timeMax": (now + timedelta(days=1)).isoformat(),
                "singleEvents": "true", "orderBy": "startTime", "maxResults": "20",
            })
        events = body.get("items") or []
        if not isinstance(events, list):
            raise ValueError("Unexpected Calendar event list")
        return [Evidence("calendar", _safe(event.get("id"), 100),
                         _safe(event.get("summary")) or "Busy event",
                         _safe(event.get("location"), 200), _https_url(event.get("htmlLink")),
                         _safe((event.get("start") or {}).get("dateTime") or
                               (event.get("start") or {}).get("date"), 100))
                for event in events[:20] if event.get("id") and event.get("status") != "cancelled"]
    if client is not None:
        return await work(client)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        return await work(http)


FETCHERS: dict[str, Callable[[str], Awaitable[list[Evidence]]]] = {
    "gmail": fetch_gmail, "drive": fetch_drive, "calendar": fetch_calendar,
}


async def fetch_source(key: str, owner: str) -> list[dict]:
    authorize_source(owner, key)
    if key not in FETCHERS:
        raise ValueError("GitHub is handled by the existing notification adapter")
    token = os.getenv(SOURCES[key].token_env, "").strip()
    if not token:
        if not has_refresh_token(owner, key):
            raise MissingCredential(f"{key} is not connected")
        token = await refreshed_access_token(owner, key)
    return [asdict(item) for item in await FETCHERS[key](token)]


def summarize_evidence(items: list[dict], statuses: dict[str, str] | None = None,
                       source_order: list[str] | None = None) -> str:
    statuses = statuses or {}
    order = source_order or list(SOURCES)
    ranks = {key: index for index, key in enumerate(order)}
    unique = {(item["source"], item["source_id"]): item for item in items}
    grouped: dict[str, list[dict]] = {}
    for item in unique.values():
        grouped.setdefault(item["source"], []).append(item)
    sources = sorted(grouped, key=lambda source: (ranks.get(source, len(ranks)), source))
    ordered = []
    while len(ordered) < 15 and any(grouped.values()):
        for source in sources:
            if grouped[source]:
                ordered.append(grouped[source].pop(0))
                if len(ordered) == 15:
                    break
    lines = [f"Read-only briefing: {len(unique)} items"]
    for item in ordered:
        detail = f" — {_safe(item.get('detail'), 160)}" if item.get("detail") else ""
        link = f" {item['url']}" if item.get("url") else ""
        lines.append(f"- [{item['source']}] {_safe(item['title'])}{detail}{link}")
    if len(unique) > len(ordered):
        lines.append(f"- {len(unique) - len(ordered)} more items")
    for source, status in statuses.items():
        if status != "completed":
            lines.append(f"- {source}: {status}")
    return "\n".join(lines)
