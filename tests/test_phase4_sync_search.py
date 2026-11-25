"""Credential-free end-to-end checks for incremental metadata sync and search."""

from pathlib import Path

import httpx
import pytest

from orchestration.search import SearchIndex
from orchestration.sync import SyncEngine, SyncRecord, SyncStore


@pytest.fixture
def indexed(monkeypatch, tmp_path):
    for key in ("GMAIL", "DRIVE", "CALENDAR"):
        monkeypatch.setenv(f"ORIN_{key}_ALLOWED_USERS", "alice")
    return SyncStore(tmp_path / "sync.db")


@pytest.mark.asyncio
async def test_gmail_full_paginated_then_history_and_expired_cursor(indexed):
    calls = []
    expired = False
    full_number = 0

    def handle(request):
        nonlocal expired, full_number
        assert request.method == "GET" and request.headers["Authorization"] == "Bearer read-token"
        assert "q" not in request.url.params
        calls.append(str(request.url))
        path = request.url.path
        if path.endswith("/profile"):
            full_number += 1
            return httpx.Response(200, json={"emailAddress": "alice@example.com",
                                             "historyId": "h1" if full_number == 1 else "h3"})
        if path.endswith("/messages"):
            if full_number >= 3:
                return httpx.Response(200, json={"messages": [{"id": "m2"}]})
            if request.url.params.get("pageToken"):
                return httpx.Response(200, json={"messages": [{"id": "m2"}]})
            return httpx.Response(200, json={"messages": [{"id": "m1"}], "nextPageToken": "p2"})
        if path.endswith("/history"):
            if expired:
                return httpx.Response(404, json={"error": "expired"})
            if request.url.params.get("pageToken"):
                return httpx.Response(200, json={"history": [{"messagesDeleted": [
                    {"message": {"id": "m1"}}]}], "historyId": "h2"})
            assert request.url.params["startHistoryId"] == "h1"
            return httpx.Response(200, json={"history": [{"messagesAdded": [
                {"message": {"id": "m3"}}]}], "nextPageToken": "next"})
        if "/messages/" in path:
            assert request.url.params["format"] == "metadata"
            mid = path.split("/")[-1]
            return httpx.Response(200, json={"id": mid, "threadId": mid, "payload": {"headers": [
                {"name": "Subject", "value": f"Project plan {mid}"},
                {"name": "From", "value": "alex@example.com"}]}})
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        engine = SyncEngine(indexed, client)
        first = await engine.sync("alice", "gmail", "alice@example.com", "read-token")
        assert (first.mode, first.upserted, first.cursor) == ("full", 2, "h1")
        second = await engine.sync("alice", "gmail", "alice@example.com", "read-token")
        assert (second.mode, second.upserted, second.deleted, second.cursor) == ("incremental", 1, 1, "h2")
        assert {row["source_id"] for row in indexed.records("alice")} == {"m2", "m3"}
        expired = True
        third = await engine.sync("alice", "gmail", "alice@example.com", "read-token")
        assert (third.mode, third.cursor) == ("full", "h3")
        assert {row["source_id"] for row in indexed.records("alice")} == {"m2"}
    assert len(calls) >= 10
    assert indexed.records("bob") == []


@pytest.mark.asyncio
async def test_drive_full_change_pages_and_expired_cursor(indexed):
    calls = []
    expired = False

    def handle(request):
        nonlocal expired
        assert request.method == "GET"
        calls.append(str(request.url))
        path = request.url.path
        if path.endswith("/about"):
            assert request.url.params["fields"] == "user(emailAddress)"
            return httpx.Response(200, json={"user": {"emailAddress": "alice@example.com"}})
        if path.endswith("/changes/startPageToken"):
            return httpx.Response(200, json={"startPageToken": "start"})
        if path.endswith("/files"):
            if request.url.params.get("pageToken"):
                return httpx.Response(200, json={"files": [{"id": "f2", "name": "Plan B"}]})
            return httpx.Response(200, json={"files": [{"id": "f1", "name": "Plan A"}],
                                             "nextPageToken": "files-next"})
        if path.endswith("/changes"):
            if expired:
                return httpx.Response(410, json={"error": "expired"})
            if request.url.params.get("pageToken") == "change-next":
                return httpx.Response(200, json={"changes": [{"fileId": "f3", "file": {
                    "id": "f3", "name": "Plan C"}}], "newStartPageToken": "new-start"})
            assert request.url.params["pageToken"] == "start"
            return httpx.Response(200, json={"changes": [{"fileId": "f1", "removed": True}],
                                             "nextPageToken": "change-next"})
        raise AssertionError(path)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        engine = SyncEngine(indexed, client)
        assert (await engine.sync("alice", "drive", "alice@example.com", "read-token")).mode == "full"
        update = await engine.sync("alice", "drive", "alice@example.com", "read-token")
        assert (update.mode, update.deleted, update.cursor) == ("incremental", 1, "new-start")
        assert {row["source_id"] for row in indexed.records("alice")} == {"f2", "f3"}
        expired = True
        recovered = await engine.sync("alice", "drive", "alice@example.com", "read-token")
        assert recovered.mode == "full"
        assert {row["source_id"] for row in indexed.records("alice")} == {"f1", "f2"}
    assert all("alt=media" not in url for url in calls)


@pytest.mark.asyncio
async def test_calendar_sync_token_410_and_atomic_failure(indexed):
    stale = False
    fail_page = False
    seen = []

    def handle(request):
        nonlocal stale, fail_page
        assert request.method == "GET"
        seen.append(dict(request.url.params))
        if request.url.params.get("syncToken"):
            assert "timeMin" not in request.url.params and "orderBy" not in request.url.params
            if stale:
                return httpx.Response(410, json={"error": "sync expired"})
            return httpx.Response(200, json={"items": [{"id": "e1", "status": "cancelled"},
                                                      {"id": "e2", "summary": "Planning review"}],
                                             "nextSyncToken": "s2"})
        if request.url.params.get("pageToken"):
            if fail_page:
                return httpx.Response(503, json={"error": "outage"})
            return httpx.Response(200, json={"items": [{"id": "e2", "summary": "Planning review"}],
                                             "nextSyncToken": "s3" if stale else "s1"})
        return httpx.Response(200, json={"items": [{"id": "e1", "summary": "Design review"}],
                                         "nextPageToken": "p2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        engine = SyncEngine(indexed, client)
        fail_page = True
        with pytest.raises(httpx.HTTPStatusError):
            await engine.sync("alice", "calendar", "alice@example.com", "read-token")
        assert indexed.cursor("alice", "alice@example.com", "calendar") is None
        assert indexed.records("alice") == []
        fail_page = False
        assert (await engine.sync("alice", "calendar", "alice@example.com", "read-token")).cursor == "s1"
        assert (await engine.sync("alice", "calendar", "alice@example.com", "read-token")).cursor == "s2"
        assert {row["source_id"] for row in indexed.records("alice")} == {"e2"}
        stale = True
        assert (await engine.sync("alice", "calendar", "alice@example.com", "read-token")).mode == "full"
        assert indexed.cursor("alice", "alice@example.com", "calendar") == "s3"
    assert all("timeMin" not in params for params in seen)


@pytest.mark.asyncio
async def test_owner_grant_and_account_identity_enforced(indexed):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
        "emailAddress": "other@example.com", "historyId": "h1"}))) as client:
        engine = SyncEngine(indexed, client)
        with pytest.raises(PermissionError):
            await engine.sync("bob", "gmail", "other@example.com", "token")
        with pytest.raises(PermissionError, match="does not match"):
            await engine.sync("alice", "gmail", "alice@example.com", "token")
    assert indexed.records("alice") == []


def test_imaginary_meeting_prep_search_with_citations_and_content_boundary(indexed, tmp_path):
    search = SearchIndex(indexed)
    search.ingest_evidence("alice", [
        {"source": "gmail", "account_id": "alice@example.com", "source_id": "m1",
         "title": "Project Aurora review", "detail": "From Maya", "url": "https://mail.google.com/#all/m1",
         "fetched_at": "2026-11-25T10:00:00Z", "content_kind": "metadata"},
        {"source": "drive", "account_id": "alice@example.com", "source_id": "f1",
         "title": "Aurora launch plan", "detail": "Google Doc", "url": "https://drive.google.com/open?id=f1",
         "fetched_at": "2026-11-25T10:01:00Z", "content_kind": "metadata"},
        {"source": "calendar", "account_id": "alice@example.com", "source_id": "e1",
         "title": "Aurora planning meeting", "detail": "Room 7",
         "url": "https://calendar.google.com/calendar/event?eid=e1",
         "fetched_at": "2026-11-25T10:02:00Z", "content_kind": "metadata"},
    ])
    documents = tmp_path / "approved"
    documents.mkdir()
    (documents / "notes.md").write_text("Aurora launch questions: ask Maya about the rollout date.")
    assert search.index_local_files("alice", documents, ["notes.md"]) == 1
    metadata = search.search("alice", "Aurora", include_content=False)
    assert {hit.source for hit in metadata} == {"gmail", "drive", "calendar"}
    assert all(hit.account_id == "alice@example.com" and hit.citation.startswith("https://")
               and hit.content_kind == "metadata" and hit.fetched_at for hit in metadata)
    with_local = search.search("alice", "Aurora", include_content=True)
    assert {hit.source for hit in with_local} == {"gmail", "drive", "calendar", "filesystem"}
    assert next(hit for hit in with_local if hit.source == "filesystem").citation.startswith("file://")
    assert search.search("bob", "Aurora", include_content=True) == []
    assert len(search.search("alice", "Aurora", account_id="alice@example.com", include_content=True)) == 3
    with pytest.raises(ValueError, match="metadata grants"):
        search.ingest_evidence("alice", [{"source": "gmail", "account_id": "alice@example.com",
            "source_id": "body", "title": "Secret", "content_kind": "content"}])


def test_local_index_rejects_escape_and_symlink(indexed, tmp_path):
    search = SearchIndex(indexed)
    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("Private")
    (root / "link.md").symlink_to(outside)
    with pytest.raises(PermissionError):
        search.index_local_files("alice", root, ["../outside.md"])
    with pytest.raises(PermissionError):
        search.index_local_files("alice", root, ["link.md"])
    assert indexed.records("alice") == []
