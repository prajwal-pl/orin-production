"""Desktop Google OAuth for Orin's owner-scoped, read-only capabilities."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import keyring

from orchestration.config import load_environment


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
KEYRING_SERVICE = "orin.google.oauth"
GOOGLE_SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.metadata",
    "drive": "https://www.googleapis.com/auth/drive.metadata.readonly",
    "calendar": "https://www.googleapis.com/auth/calendar.events.readonly",
    "gmail_send": "https://www.googleapis.com/auth/gmail.send",
    "calendar_write": "https://www.googleapis.com/auth/calendar.events",
    "drive_write": "https://www.googleapis.com/auth/drive.file",
}


def client_file() -> Path:
    return Path(os.getenv("ORIN_GOOGLE_CLIENT_FILE", "~/.orion/config/google_oauth_client.json")).expanduser()


def load_client() -> dict[str, str]:
    path = client_file()
    data = json.loads(path.read_text())
    installed = data.get("installed")
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("client_secret"):
        raise ValueError("Expected a Google desktop OAuth client JSON file")
    return {"client_id": installed["client_id"], "client_secret": installed["client_secret"]}


def credential_name(owner: str, source: str) -> str:
    if source not in GOOGLE_SCOPES or not owner:
        raise ValueError("Unknown Google source or owner")
    return f"{owner}:{source}"


def has_refresh_token(owner: str, source: str) -> bool:
    if not client_file().is_file():
        return False
    try:
        return bool(keyring.get_password(KEYRING_SERVICE, credential_name(owner, source)))
    except keyring.errors.KeyringError:
        return False


def store_refresh_token(owner: str, source: str, token: str) -> None:
    if not token:
        raise ValueError("Google did not issue a refresh token")
    keyring.set_password(KEYRING_SERVICE, credential_name(owner, source), token)


def authorization_url(client_id: str, source: str, redirect_uri: str, state: str,
                      verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES[source],
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


async def exchange_code(client: dict[str, str], code: str, redirect_uri: str,
                        verifier: str, source: str) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        response = await http.post(TOKEN_URL, data={
            "client_id": client["client_id"], "client_secret": client["client_secret"],
            "code": code, "code_verifier": verifier, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    response.raise_for_status()
    payload = response.json()
    if GOOGLE_SCOPES[source] not in payload.get("scope", "").split():
        raise ValueError("Google did not grant the requested read scope")
    token = payload.get("refresh_token")
    if not token:
        raise ValueError("Google did not issue a refresh token")
    return token


async def refreshed_access_token(owner: str, source: str) -> str:
    refresh_token = keyring.get_password(KEYRING_SERVICE, credential_name(owner, source))
    if not refresh_token:
        raise ValueError(f"{source} is not connected")
    client = load_client()
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
        response = await http.post(TOKEN_URL, data={
            "client_id": client["client_id"], "client_secret": client["client_secret"],
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        })
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise ValueError("Google refresh response had no access token")
    return token


async def disconnect(owner: str, source: str, revoke_google: bool = False) -> None:
    name = credential_name(owner, source)
    token = keyring.get_password(KEYRING_SERVICE, name)
    if not token:
        return
    if revoke_google:
        # Google revocation invalidates all scopes granted to this project for
        # this account, so clear every locally stored source after success.
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            response = await http.post(REVOKE_URL, data={"token": token})
        response.raise_for_status()
        sources = GOOGLE_SCOPES
    else:
        sources = (source,)
    for item in sources:
        item_name = credential_name(owner, item)
        if keyring.get_password(KEYRING_SERVICE, item_name):
            keyring.delete_password(KEYRING_SERVICE, item_name)


def _receive_code(expected_state: str) -> tuple[str, dict[str, str], HTTPServer]:
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            callback = urlsplit(self.path)
            if callback.path != "/callback":
                self.send_error(404)
                return
            query = parse_qs(callback.query)
            if query.get("state", [""])[0] != expected_state:
                self.send_error(400, "OAuth state mismatch")
                return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            self.send_response(200 if result["code"] else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Orin received Google's response. You can close this tab.")

        def log_message(self, _format, *_args):
            pass  # Never log the authorization code or callback query.

    server = HTTPServer(("127.0.0.1", 0), Callback)
    server.timeout = 180
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    return redirect_uri, result, server


async def connect(source: str, owner: str, open_browser: bool = False) -> None:
    client = load_client()
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    redirect_uri, result, server = _receive_code(state)
    url = authorization_url(client["client_id"], source, redirect_uri, state, verifier)
    print(f"Open this URL to authorize {source} for {owner}:\n{url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        await asyncio.to_thread(server.handle_request)
    finally:
        server.server_close()
    if result.get("error"):
        raise RuntimeError(f"Google authorization failed: {result['error']}")
    if not result.get("code"):
        raise TimeoutError("No valid Google OAuth callback received")
    refresh_token = await exchange_code(client, result["code"], redirect_uri, verifier, source)
    store_refresh_token(owner, source, refresh_token)
    print(f"Connected {source} for {owner}; refresh token stored in the OS credential store.")


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description="Connect a Google read capability to Orin")
    parser.add_argument("source", choices=GOOGLE_SCOPES)
    parser.add_argument("--owner", default=os.getenv("ORIN_CLI_USER", "local"))
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--disconnect", action="store_true", help="Remove this source's local credential")
    parser.add_argument("--revoke-google", action="store_true",
                        help="Revoke this Google grant; Google invalidates all Orin scopes for the account")
    args = parser.parse_args()
    if args.revoke_google and not args.disconnect:
        parser.error("--revoke-google requires --disconnect")
    if args.disconnect:
        asyncio.run(disconnect(args.owner, args.source, args.revoke_google))
        print(f"Disconnected {args.source} for {args.owner}.")
    else:
        asyncio.run(connect(args.source, args.owner, args.open_browser))


if __name__ == "__main__":
    main()
