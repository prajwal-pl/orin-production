"""Credential-free provider contract checks for optional Phase 4 sources."""

import httpx
import pytest

from orchestration import external_reads, integrations


@pytest.mark.asyncio
async def test_optional_sources_return_bounded_cited_evidence(monkeypatch):
    monkeypatch.setenv("ORIN_SLACK_CHANNEL_IDS", "C123")
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.notion.com":
            assert request.method == "POST" and request.url.path == "/v1/search"
            assert request.headers["Notion-Version"] == external_reads.NOTION_VERSION
            return httpx.Response(200, json={"results": [{"object": "page", "id": "note-1",
                "url": "https://www.notion.so/note-1", "last_edited_time": "2026-11-25T09:00:00Z",
                "properties": {"Name": {"type": "title", "title": [{"plain_text": "Design notes"}]}}}]})
        if request.url.host == "api.todoist.com":
            assert request.method == "GET" and request.url.path == "/api/v1/tasks"
            return httpx.Response(200, json={"results": [{"id": "task-1", "content": "Send proposal",
                "due": {"date": "2026-11-26"}}]})
        if request.url.host == "slack.com":
            assert request.method == "GET" and request.url.params["channel"] == "C123"
            return httpx.Response(200, json={"ok": True, "messages": [
                {"ts": "1234.000001", "text": "Decision: launch Friday"}]})
        if request.url.host == "graph.microsoft.com":
            assert request.method == "GET" and "body" not in request.url.params["$select"]
            return httpx.Response(200, json={"value": [{"id": "mail-1", "subject": "Project update",
                "webLink": "https://outlook.office.com/mail/id/mail-1",
                "receivedDateTime": "2026-11-25T09:00:00Z"}]})
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        results = {key: await external_reads.fetch_external_source(key, "token", "account-1", client)
                   for key in external_reads.FETCHERS}
    assert len(seen) == 4
    assert {key: rows[0]["title"] for key, rows in results.items()} == {
        "notion": "Design notes", "todoist": "Send proposal",
        "slack": "Decision: launch Friday", "microsoft": "Project update"}
    assert all(rows[0]["account_id"] == "account-1" and rows[0]["url"].startswith("https://")
               and rows[0]["fetched_at"] for rows in results.values())
    assert results["slack"][0]["content_kind"] == "content"
    assert results["microsoft"][0]["content_kind"] == "metadata"


@pytest.mark.asyncio
async def test_optional_sources_require_owner_grant_and_credential(monkeypatch):
    monkeypatch.setenv("ORIN_NOTION_ALLOWED_USERS", "alice")
    monkeypatch.delenv("ORIN_NOTION_TOKEN", raising=False)
    with pytest.raises(PermissionError):
        await integrations.fetch_source("notion", "bob")
    with pytest.raises(integrations.MissingCredential):
        await integrations.fetch_source("notion", "alice")


@pytest.mark.asyncio
async def test_slack_rejects_non_literal_channel_ids(monkeypatch):
    monkeypatch.setenv("ORIN_SLACK_CHANNEL_IDS", "C123/../../other")
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: pytest.fail("Invalid channel must not make a request"))) as client:
        with pytest.raises(ValueError, match="Invalid Slack channel"):
            await external_reads.fetch_external_source("slack", "token", "account", client)
