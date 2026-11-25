"""Bounded read adapters for optional productivity services.

These adapters return evidence only. Account tokens and grants are resolved at
the shared capability boundary in ``integrations.fetch_source``.
"""

from datetime import datetime, timezone
from urllib.parse import quote, urlparse
import os

import httpx


NOTION_VERSION = "2026-03-11"


def _text(value: object, limit: int = 300) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ")[:limit]


def _url(value: object, expected_host: str) -> str:
    candidate = _text(value, 500)
    parsed = urlparse(candidate)
    return candidate if parsed.scheme == "https" and parsed.hostname == expected_host else ""


def _evidence(source: str, source_id: object, title: object, detail: object,
              url: object, occurred_at: object, account_id: str,
              content_kind: str = "metadata") -> dict:
    return {"source": source, "source_id": _text(source_id, 120),
            "title": _text(title) or "Untitled", "detail": _text(detail),
            "url": _text(url, 500), "occurred_at": _text(occurred_at, 100),
            "account_id": _text(account_id, 120),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_kind": content_kind}


async def _json(response: httpx.Response) -> dict:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Unexpected source response")
    return body


async def fetch_notion(token: str, account_id: str, client: httpx.AsyncClient) -> list[dict]:
    items: list[dict] = []
    cursor = None
    for _ in range(3):
        payload = {"page_size": 50, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
        if cursor:
            payload["start_cursor"] = cursor
        body = await _json(await client.post("https://api.notion.com/v1/search", json=payload, headers={
            "Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION}))
        for page in body.get("results", [])[:50]:
            if not isinstance(page, dict) or page.get("object") != "page" or not page.get("id"):
                continue
            properties = page.get("properties") or {}
            title_property = next((prop for prop in properties.values()
                                   if isinstance(prop, dict) and prop.get("type") == "title"), {})
            rich = title_property.get("title") or []
            title = "".join(_text(part.get("plain_text"), 150) for part in rich if isinstance(part, dict))
            items.append(_evidence("notion", page["id"], title or "Untitled page", "Page title",
                                   _url(page.get("url"), "www.notion.so") or
                                   f"https://www.notion.so/{quote(str(page['id']), safe='')}",
                                   page.get("last_edited_time"), account_id))
        cursor = body.get("next_cursor") if body.get("has_more") else None
        if not cursor:
            break
    return items


async def fetch_todoist(token: str, account_id: str, client: httpx.AsyncClient) -> list[dict]:
    items: list[dict] = []
    cursor = None
    for _ in range(3):
        params = {"limit": "50"}
        if cursor:
            params["cursor"] = cursor
        body = await _json(await client.get("https://api.todoist.com/api/v1/tasks", params=params,
                                           headers={"Authorization": f"Bearer {token}"}))
        for task in body.get("results", [])[:50]:
            if not isinstance(task, dict) or not task.get("id"):
                continue
            task_id = _text(task["id"], 100)
            due = task.get("due") or {}
            items.append(_evidence("todoist", task_id, task.get("content"),
                                   f"Due {due.get('date', 'unscheduled')}",
                                   f"https://app.todoist.com/app/task/{quote(task_id, safe='')}",
                                   due.get("date") or task.get("updated_at"), account_id,
                                   "content"))
        cursor = body.get("next_cursor")
        if not cursor:
            break
    return items


async def fetch_slack(token: str, account_id: str, client: httpx.AsyncClient) -> list[dict]:
    channels = [part.strip() for part in os.getenv("ORIN_SLACK_CHANNEL_IDS", "").split(",") if part.strip()]
    items: list[dict] = []
    for channel in channels[:5]:
        if not channel.isalnum():
            raise ValueError("Invalid Slack channel ID")
        body = await _json(await client.get("https://slack.com/api/conversations.history",
                                           params={"channel": channel, "limit": "20"},
                                           headers={"Authorization": f"Bearer {token}"}))
        if not body.get("ok"):
            raise ValueError("Slack history request failed")
        for message in body.get("messages", [])[:20]:
            if not isinstance(message, dict) or not message.get("ts"):
                continue
            stamp = _text(message["ts"], 30)
            items.append(_evidence("slack", f"{channel}:{stamp}",
                                   _text(message.get("text"), 160) or "Slack message",
                                   f"Channel {channel}",
                                   f"https://app.slack.com/archives/{channel}/p{stamp.replace('.', '')}",
                                   stamp, account_id, "content"))
    return items


async def fetch_microsoft(token: str, account_id: str, client: httpx.AsyncClient) -> list[dict]:
    body = await _json(await client.get("https://graph.microsoft.com/v1.0/me/messages",
                                       params={"$select": "id,subject,receivedDateTime,webLink,from,isRead",
                                               "$top": "20"},
                                       headers={"Authorization": f"Bearer {token}"}))
    return [_evidence("microsoft", mail["id"], mail.get("subject") or "(no subject)",
                      ((mail.get("from") or {}).get("emailAddress") or {}).get("name", ""),
                      _url(mail.get("webLink"), "outlook.office.com") or "",
                      mail.get("receivedDateTime"), account_id)
            for mail in body.get("value", [])[:20] if isinstance(mail, dict) and mail.get("id")]


FETCHERS = {"notion": fetch_notion, "todoist": fetch_todoist,
            "slack": fetch_slack, "microsoft": fetch_microsoft}


async def fetch_external_source(key: str, token: str, account_id: str,
                                client: httpx.AsyncClient | None = None) -> list[dict]:
    if key not in FETCHERS:
        raise ValueError("Unknown external read source")
    if client is not None:
        return await FETCHERS[key](token, account_id, client)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        return await FETCHERS[key](token, account_id, http)
