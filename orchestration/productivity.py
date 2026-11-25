"""Read-only meeting preparation and follow-up suggestions from cited evidence."""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse


STOP = {"about", "after", "before", "from", "have", "meeting", "with", "your",
        "this", "that", "please", "today", "tomorrow", "recent", "review"}
FOLLOW_UP_CUES = {"reply", "respond", "action", "approve", "approval", "deadline",
                  "follow", "decision", "confirm", "feedback"}


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]{3,}", value.lower()) if term not in STOP}


def _safe(value: object, limit: int = 250) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ")[:limit]


def _validate(owner: str, item: dict) -> dict:
    if item.get("owner", owner) != owner:
        raise PermissionError("Cross-owner evidence is not available")
    required = ("source", "source_id", "account_id", "title", "fetched_at", "content_kind")
    if any(not item.get(key) for key in required):
        raise ValueError("Evidence lacks source, account, identity, freshness, or type")
    parsed = datetime.fromisoformat(str(item["fetched_at"]).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidence freshness must include a timezone")
    if item["content_kind"] != "metadata":
        raise ValueError("This workflow accepts metadata only")
    link = _safe(item.get("url"), 600)
    if link and urlparse(link).scheme not in {"https", "file"}:
        raise ValueError("Evidence citation must be HTTPS or a local file URL")
    return {
        "source": _safe(item["source"], 50), "source_id": _safe(item["source_id"], 150),
        "account_id": _safe(item["account_id"], 150), "title": _safe(item["title"]),
        "detail": _safe(item.get("detail")), "url": link,
        "occurred_at": _safe(item.get("occurred_at"), 100),
        "fetched_at": parsed.astimezone(timezone.utc).isoformat(), "content_kind": "metadata",
    }


def _citation(item: dict) -> dict:
    return {key: item[key] for key in
            ("source", "source_id", "account_id", "title", "url", "fetched_at", "content_kind")}


def prepare_meeting(owner: str, event: dict, evidence: list[dict], *, limit: int = 5) -> dict:
    """Return cited, metadata-only context related to a calendar event title."""
    if limit < 1 or limit > 20:
        raise ValueError("Meeting context limit must be between 1 and 20")
    meeting = _validate(owner, event)
    if meeting["source"] != "calendar":
        raise ValueError("Meeting preparation requires a Calendar event")
    query_terms = _terms(meeting["title"])
    ranked = []
    seen = set()
    for item in evidence:
        candidate = _validate(owner, item)
        key = (candidate["source"], candidate["account_id"], candidate["source_id"])
        if key in seen or key == (meeting["source"], meeting["account_id"], meeting["source_id"]):
            continue
        seen.add(key)
        overlap = len(query_terms & _terms(candidate["title"] + " " + candidate["detail"]))
        if overlap:
            ranked.append((overlap, candidate["fetched_at"], candidate))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]["source_id"]))
    related = [candidate for _, _, candidate in ranked[:limit]]
    questions = [candidate["title"] for candidate in related
                 if "?" in candidate["title"] or "question" in candidate["title"].lower()]
    return {"meeting": meeting, "related": related, "open_questions": questions[:3],
            "citations": [_citation(meeting), *(_citation(item) for item in related)],
            "note": "Metadata matches only; open cited sources to verify context."}


def follow_up_queue(owner: str, evidence: list[dict], *, limit: int = 12) -> list[dict]:
    """Suggest review candidates, without asserting a reply is due or writing tasks."""
    if limit < 1 or limit > 50:
        raise ValueError("Follow-up limit must be between 1 and 50")
    found = []
    seen = set()
    for raw in evidence:
        item = _validate(owner, raw)
        key = (item["source"], item["account_id"], item["source_id"])
        if key in seen:
            continue
        seen.add(key)
        words = _terms(item["title"])
        if item["source"] == "github" and any(cue in item["detail"].lower()
                                                   for cue in ("review_requested", "assign", "mention")):
            reason = "GitHub notification explicitly requests attention"
            priority = 0
        elif item["source"] == "calendar" and words & {"deadline", "due"}:
            reason = "Calendar title suggests a deadline; verify details"
            priority = 1
        elif item["source"] == "gmail" and words & FOLLOW_UP_CUES:
            reason = "Email subject suggests follow-up; inspect the message before acting"
            priority = 2
        else:
            continue
        found.append((priority, item["fetched_at"], item, reason))
    found.sort(key=lambda row: (row[0], row[1], row[2]["source_id"]))
    return [{"reason": reason, "evidence": item, "citation": _citation(item)}
            for _, _, item, reason in found[:limit]]
