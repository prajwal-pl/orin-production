"""Ephemeral, single-owner browser sessions for the loopback control center."""

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request


COOKIE_NAME = "orin_session"
SESSION_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class BrowserSession:
    owner: str
    csrf: str
    expires_at: float


class WebAuth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pair_hash: str | None = None
        self._pair_owner: str | None = None
        self._sessions: dict[str, BrowserSession] = {}

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def start_pairing(self, owner: str) -> str:
        if not owner:
            raise ValueError("A local owner is required")
        code = secrets.token_urlsafe(10)
        with self._lock:
            self._pair_hash = self._hash(code)
            self._pair_owner = owner
            self._sessions.clear()
        return code

    def pairing_available(self) -> bool:
        with self._lock:
            return self._pair_hash is not None

    def pair(self, code: str) -> tuple[str, BrowserSession]:
        if not code or len(code) > 100:
            raise HTTPException(403, "Invalid pairing code")
        with self._lock:
            if self._pair_hash is None or self._pair_owner is None:
                raise HTTPException(403, "Pairing is unavailable; restart the local control center")
            if not secrets.compare_digest(self._pair_hash, self._hash(code)):
                raise HTTPException(403, "Invalid pairing code")
            token = secrets.token_urlsafe(32)
            session = BrowserSession(self._pair_owner, secrets.token_urlsafe(32),
                                     time.time() + SESSION_SECONDS)
            self._sessions[self._hash(token)] = session
            self._pair_hash = None
            self._pair_owner = None
        return token, session

    def session(self, token: str | None) -> BrowserSession | None:
        if not token:
            return None
        digest = self._hash(token)
        with self._lock:
            session = self._sessions.get(digest)
            if session is not None and session.expires_at <= time.time():
                del self._sessions[digest]
                return None
            return session

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(self._hash(token), None)

    @staticmethod
    def check_origin(request: Request) -> None:
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if request.headers.get("origin") != expected:
            raise HTTPException(403, "Request origin is not the control center")

    def authorize_cookie(self, request: Request, owner_header: str | None) -> BrowserSession:
        session = self.session(request.cookies.get(COOKIE_NAME))
        if session is None:
            raise HTTPException(401, "Browser session is unavailable or expired")
        if owner_header is not None and owner_header != session.owner:
            raise HTTPException(403, "Forbidden")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.check_origin(request)
            supplied = request.headers.get("x-orin-csrf", "")
            if not supplied or not secrets.compare_digest(supplied, session.csrf):
                raise HTTPException(403, "A valid CSRF token is required")
        return session


web_auth = WebAuth()
