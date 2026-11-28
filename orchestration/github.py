"""Read-only GitHub notification capability."""

import os
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

from orchestration.integrations import MissingCredential


@dataclass(frozen=True)
class Capability:
    name: str
    input_type: type
    output_type: type
    permission: str
    timeout_seconds: int


GITHUB_NOTIFICATIONS = Capability("github.notifications.read", dict, list, "github:notifications", 20)
CAPABILITIES = {GITHUB_NOTIFICATIONS.name: GITHUB_NOTIFICATIONS}


def authorize_notifications(owner: str):
    allowed = {value.strip() for value in os.getenv("ORIN_GITHUB_ALLOWED_USERS", "local").split(",")}
    if owner not in allowed:
        raise PermissionError("GitHub notifications access is not enabled for this user")


def notification_link(repository: str, subject_url: str | None) -> str:
    parsed = urlparse(subject_url or "")
    path = parsed.path
    if parsed.scheme == "https" and parsed.netloc == "api.github.com" and path.startswith("/repos/"):
        browser_path = path.removeprefix("/repos/").replace("/pulls/", "/pull/")
        return "https://github.com/" + browser_path
    return "https://github.com/notifications?query=repo%3A" + quote(repository, safe="")


async def fetch_notifications() -> list[dict]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise MissingCredential(
            "GitHub is not connected; add GITHUB_TOKEN to the local configuration, then resume"
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    notifications = []
    async with httpx.AsyncClient(base_url="https://api.github.com", timeout=GITHUB_NOTIFICATIONS.timeout_seconds,
                                 follow_redirects=False) as client:
        page = 1
        while True:
            response = await client.get("/notifications", headers=headers, params={"per_page": 50, "page": page, "all": "false"})
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list):
                raise ValueError("Unexpected GitHub notification response")
            for item in batch:
                repository = item.get("repository") or {}
                subject = item.get("subject") or {}
                notifications.append({
                    "repository": repository.get("full_name", "unknown repository"),
                    "title": subject.get("title", "Untitled"),
                    "reason": item.get("reason", "unknown"),
                    "url": notification_link(repository.get("full_name", ""), subject.get("url")),
                })
            if len(batch) < 50:
                break
            page += 1
    return notifications


def summarize_notifications(items: list[dict], priority_reasons: list[str] | None = None) -> str:
    if not items:
        return "You have no unread GitHub notifications."
    important = {"mention", "team_mention", "assign", "review_requested", "security_alert"}
    unique_items = list({
        (item["repository"], item["title"], item["reason"], item["url"]): item
        for item in items
    }.values())
    grouped: dict[str, list[dict]] = {}
    for item in unique_items:
        grouped.setdefault(item["repository"], []).append(item)
    lines = [f"Unread GitHub notifications: {len(unique_items)}"]
    for repository, entries in sorted(grouped.items()):
        lines.append(f"\n{repository} ({len(entries)})")
        if priority_reasons is None:
            ordered = sorted(entries, key=lambda entry: entry["reason"] not in important)
        else:
            ranks = {reason: index for index, reason in enumerate(priority_reasons)}
            ordered = sorted(entries, key=lambda entry: ranks.get(entry["reason"], len(ranks)))
        for item in ordered[:10]:
            priority = "Attention: " if item["reason"] in important else ""
            lines.append(f"- {priority}{item['title']} ({item['reason']}) {item['url']}")
        if len(entries) > 10:
            lines.append(f"- {len(entries) - 10} more notifications")
    return "\n".join(lines)
