import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from orchestration import google_oauth, integrations


def test_authorization_url_is_scoped_and_uses_pkce():
    verifier = "test-verifier" * 5
    url = google_oauth.authorization_url("desktop-client", "gmail", "http://127.0.0.1:1234/callback",
                                         "random-state", verifier)
    query = parse_qs(urlsplit(url).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["scope"] == [google_oauth.GOOGLE_SCOPES["gmail"]]
    assert query["code_challenge"] == [expected]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["random-state"]
    assert query["access_type"] == ["offline"]


@pytest.mark.asyncio
async def test_token_exchange_validates_scope_and_refresh_is_owner_scoped(monkeypatch, tmp_path):
    client_path = tmp_path / "client.json"
    client_path.write_text('{"installed":{"client_id":"client","client_secret":"secret"}}')
    monkeypatch.setenv("ORIN_GOOGLE_CLIENT_FILE", str(client_path))
    credentials = {}
    monkeypatch.setattr(google_oauth.keyring, "set_password",
                        lambda service, name, value: credentials.__setitem__((service, name), value))
    monkeypatch.setattr(google_oauth.keyring, "get_password",
                        lambda service, name: credentials.get((service, name)))
    requests = []

    def respond(request):
        requests.append(request)
        form = parse_qs(request.content.decode())
        assert request.method == "POST" and request.url == google_oauth.TOKEN_URL
        if form["grant_type"] == ["authorization_code"]:
            assert form["code_verifier"] == ["verifier"]
            return httpx.Response(200, json={"refresh_token": "refresh", "scope":
                google_oauth.GOOGLE_SCOPES["drive"]})
        assert form["refresh_token"] == ["refresh"]
        return httpx.Response(200, json={"access_token": "short-lived-access"})

    transport = httpx.MockTransport(respond)
    original = httpx.AsyncClient
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=transport, **kwargs))
    client = google_oauth.load_client()
    refresh = await google_oauth.exchange_code(client, "code", "http://127.0.0.1/callback",
                                                "verifier", "drive")
    google_oauth.store_refresh_token("alice", "drive", refresh)
    assert google_oauth.has_refresh_token("alice", "drive")
    assert not google_oauth.has_refresh_token("bob", "drive")
    assert not google_oauth.has_refresh_token("alice", "gmail")
    assert await google_oauth.refreshed_access_token("alice", "drive") == "short-lived-access"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_token_exchange_rejects_missing_scope(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "refresh_token": "refresh", "scope": google_oauth.GOOGLE_SCOPES["calendar"]}))
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(ValueError, match="requested read scope"):
        await google_oauth.exchange_code({"client_id": "client", "client_secret": "secret"},
                                         "code", "http://127.0.0.1/callback", "verifier", "gmail")


@pytest.mark.asyncio
async def test_google_source_refreshes_without_environment_token(monkeypatch):
    monkeypatch.setenv("ORIN_GMAIL_ALLOWED_USERS", "alice")
    monkeypatch.delenv("ORIN_GMAIL_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(integrations, "has_refresh_token", lambda owner, source: (owner, source) == ("alice", "gmail"))
    async def refresh(owner, source):
        assert (owner, source) == ("alice", "gmail")
        return "access"
    async def fetch(token):
        assert token == "access"
        return [integrations.Evidence("gmail", "id", "Subject", "", "")]
    monkeypatch.setattr(integrations, "refreshed_access_token", refresh)
    monkeypatch.setitem(integrations.FETCHERS, "gmail", fetch)
    assert (await integrations.fetch_source("gmail", "alice"))[0]["title"] == "Subject"
    with pytest.raises(PermissionError):
        await integrations.fetch_source("gmail", "bob")


@pytest.mark.asyncio
async def test_loopback_callback_rejects_wrong_state():
    redirect_uri, result, server = google_oauth._receive_code("correct")
    try:
        worker = asyncio.create_task(asyncio.to_thread(server.handle_request))
        async with httpx.AsyncClient() as client:
            response = await client.get(redirect_uri + "?state=wrong&code=stolen")
        await worker
        assert response.status_code == 400
        assert result == {}
    finally:
        server.server_close()


@pytest.mark.asyncio
async def test_remote_revocation_clears_all_local_google_grants(monkeypatch):
    credentials = {(google_oauth.KEYRING_SERVICE, f"alice:{source}"): f"{source}-refresh"
                   for source in google_oauth.GOOGLE_SCOPES}
    monkeypatch.setattr(google_oauth.keyring, "get_password",
                        lambda service, name: credentials.get((service, name)))
    monkeypatch.setattr(google_oauth.keyring, "delete_password",
                        lambda service, name: credentials.pop((service, name)))
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200)
    original = httpx.AsyncClient
    monkeypatch.setattr(google_oauth.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    await google_oauth.disconnect("alice", "gmail", revoke_google=True)
    assert not credentials
    assert len(seen) == 1 and seen[0].url == google_oauth.REVOKE_URL
    assert parse_qs(seen[0].content.decode())["token"] == ["gmail-refresh"]
