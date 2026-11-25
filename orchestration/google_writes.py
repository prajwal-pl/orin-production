"""Narrow Google write operations for the approved action service.

Provider calls are intentionally separate from approval and idempotency. Callers
must validate and claim a durable action before using these functions.
"""

import base64
import hashlib
import re
from datetime import datetime
from email.message import EmailMessage

import httpx


WRITE_SOURCES = {
    "gmail.send": "gmail_send",
    "calendar.events.create": "calendar_write",
    "drive.folder.create": "drive_write",
}


def validate_write(capability: str, parameters: dict) -> dict:
    if capability == "gmail.send":
        if set(parameters) != {"to", "subject", "body"}:
            raise ValueError("Gmail send requires to, subject, and body")
        recipient = parameters["to"]
        subject = parameters["subject"]
        body = parameters["body"]
        if not isinstance(recipient, str) or not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", recipient):
            raise ValueError("One valid recipient is required")
        if not isinstance(subject, str) or not subject.strip() or "\n" in subject or "\r" in subject or len(subject) > 200:
            raise ValueError("Invalid email subject")
        if not isinstance(body, str) or len(body) > 20_000:
            raise ValueError("Email body exceeds limit")
        return {"to": recipient, "subject": subject.strip(), "body": body}
    if capability == "calendar.events.create":
        if set(parameters) != {"summary", "start", "end"}:
            raise ValueError("Calendar create requires summary, start, and end")
        summary = parameters["summary"]
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 200:
            raise ValueError("Invalid event summary")
        if not isinstance(parameters["start"], str) or not isinstance(parameters["end"], str):
            raise ValueError("Event times must be ISO strings")
        try:
            start = datetime.fromisoformat(parameters["start"])
            end = datetime.fromisoformat(parameters["end"])
        except ValueError:
            raise ValueError("Event times must be ISO timestamps") from None
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("Event start and end require offsets and increasing time")
        return {"summary": summary.strip(), "start": start.isoformat(), "end": end.isoformat()}
    if capability == "drive.folder.create":
        if set(parameters) != {"name"}:
            raise ValueError("Drive folder create requires a name")
        name = parameters["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or "/" in name:
            raise ValueError("Invalid folder name")
        return {"name": name.strip()}
    raise ValueError("Unknown Google write capability")


def calendar_event_id(owner: str, idempotency_key: str) -> str:
    # Google Calendar permits lowercase a-v and digits 0-9 in custom event IDs.
    return hashlib.sha256(f"{owner}:{idempotency_key}".encode()).hexdigest()[:32]


async def execute_google_write(capability: str, parameters: dict, token: str,
                               owner: str, idempotency_key: str,
                               client: httpx.AsyncClient | None = None) -> dict:
    params = validate_write(capability, parameters)
    if client is None:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            return await execute_google_write(capability, params, token, owner, idempotency_key, http)
    headers = {"Authorization": f"Bearer {token}"}
    if capability == "gmail.send":
        message = EmailMessage()
        message["To"] = params["to"]
        message["Subject"] = params["subject"]
        message["Message-ID"] = f"<{calendar_event_id(owner, idempotency_key)}@orin.local>"
        message.set_content(params["body"])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        response = await client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                     headers=headers, json={"raw": raw})
        response.raise_for_status()
        return {"provider_id": response.json().get("id", ""), "status": "sent"}
    if capability == "calendar.events.create":
        event_id = calendar_event_id(owner, idempotency_key)
        event = {"id": event_id, "summary": params["summary"],
                 "start": {"dateTime": params["start"]}, "end": {"dateTime": params["end"]}}
        response = await client.post("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                                     headers=headers, params={"sendUpdates": "none"}, json=event)
        if response.status_code == 409:
            response = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}", headers=headers)
            response.raise_for_status()
            existing = response.json()
            if (existing.get("summary") != params["summary"] or
                    (existing.get("start") or {}).get("dateTime") != params["start"] or
                    (existing.get("end") or {}).get("dateTime") != params["end"]):
                raise ValueError("Calendar ID collision with different event")
        else:
            response.raise_for_status()
        return {"provider_id": event_id, "status": "created"}
    if capability == "drive.folder.create":
        # App-created folders are discoverable by action ID after an ambiguous
        # response. Never automatically repeat a create after a timeout.
        action_hash = calendar_event_id(owner, idempotency_key)
        response = await client.post("https://www.googleapis.com/drive/v3/files",
                                     headers=headers, params={"fields": "id,webViewLink"},
                                     json={"name": params["name"],
                                           "mimeType": "application/vnd.google-apps.folder",
                                           "appProperties": {"orin_action_id": action_hash}})
        response.raise_for_status()
        return {"provider_id": response.json().get("id", ""), "status": "created"}
    raise ValueError("Unknown Google write capability")


async def reconcile_google_write(capability: str, token: str, owner: str,
                                 idempotency_key: str, parameters: dict,
                                 client: httpx.AsyncClient | None = None) -> dict | None:
    """Read provider state after an ambiguous write; never re-send the write."""
    if client is None:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            return await reconcile_google_write(capability, token, owner, idempotency_key,
                                                parameters, http)
    expected = validate_write(capability, parameters)
    headers = {"Authorization": f"Bearer {token}"}
    action_hash = calendar_event_id(owner, idempotency_key)
    if capability == "calendar.events.create":
        response = await client.get(
            f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{action_hash}", headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        existing = response.json()
        if (existing.get("summary") != expected["summary"] or
                (existing.get("start") or {}).get("dateTime") != expected["start"] or
                (existing.get("end") or {}).get("dateTime") != expected["end"]):
            raise ValueError("Calendar event does not match the approved action")
        return {"provider_id": action_hash, "status": "created"}
    if capability == "drive.folder.create":
        response = await client.get("https://www.googleapis.com/drive/v3/files", headers=headers,
                                    params={"q": f"appProperties has {{ key='orin_action_id' and value='{action_hash}' }} and trashed = false",
                                            "fields": "files(id,name),nextPageToken", "pageSize": "2"})
        response.raise_for_status()
        files = response.json().get("files") or []
        if len(files) == 1 and files[0].get("name") == expected["name"]:
            return {"provider_id": files[0]["id"], "status": "created"}
        if len(files) == 1:
            raise ValueError("Drive folder does not match the approved action")
        if len(files) > 1:
            raise ValueError("More than one Drive folder matches the action")
        return None
    # gmail.send cannot read Sent with a send-only scope. The owner must inspect
    # Gmail manually before any new send action is prepared.
    return None
