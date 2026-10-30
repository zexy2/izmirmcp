"""Optional static Bearer API keys.

Authentication is off unless keys are configured, so the default local setup
stays frictionless. Keys are compared as SHA-256 digests and never stored or
logged in plaintext.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.storage.quota import QuotaError, QuotaStore

KEY_PATTERN = re.compile(r"[A-Za-z0-9._~-]{32,256}", re.ASCII)
PROTECTED_PATHS = {"/status"}


def validate_api_keys(keys: tuple[str, ...]) -> None:
    if len(keys) > 100 or len(set(keys)) != len(keys) or any(not KEY_PATTERN.fullmatch(key) for key in keys):
        raise ValueError("IZMIR_MCP_API_KEYS must contain 1-100 unique 32-256 character URL-safe keys")


def _is_protected(path: str) -> bool:
    return path == "/status" or path == "/mcp" or path.startswith("/mcp/")


class ApiKeyAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        keys: tuple[str, ...],
        quota_path: str | None = None,
        daily_quota: int = 0,
    ):
        self.app = app
        self.daily_quota = max(0, int(daily_quota))
        self.quota = QuotaStore(quota_path) if quota_path and self.daily_quota else None
        self.key_hashes = tuple(hashlib.sha256(key.encode("ascii")).hexdigest() for key in keys)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.key_hashes:
            await self.app(scope, receive, send)
            return
        if not _is_protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        matched = self._match_key(scope)
        if matched is not None and self.quota is not None:
            try:
                decision = self.quota.consume(matched, limit=self.daily_quota)
            except QuotaError:
                # Fail closed: a broken quota store must not grant free access.
                response = JSONResponse(
                    {
                        "ok": False,
                        "error_code": "quota_unavailable",
                        "summary": "Usage quota could not be verified.",
                    },
                    status_code=503,
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            if not decision.allowed:
                response = JSONResponse(
                    {
                        "ok": False,
                        "error_code": "quota_exceeded",
                        "summary": "Daily request quota for this API key is exhausted.",
                    },
                    status_code=429,
                    headers={
                        "Retry-After": str(decision.retry_after_seconds),
                        "Cache-Control": "no-store",
                    },
                )
                await response(scope, receive, send)
                return
        if matched is not None:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {
                "ok": False,
                "error_code": "unauthorized",
                "summary": "A valid Bearer API key is required.",
            },
            status_code=401,
            headers={
                "WWW-Authenticate": 'Bearer realm="izmir-mcp"',
                "Cache-Control": "no-store",
            },
        )
        await response(scope, receive, send)

    def _match_key(self, scope: Scope) -> str | None:
        """Return the matched key hash (never the plaintext) or ``None``."""
        headers = [
            value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"authorization"
        ]
        if len(headers) != 1:
            return None
        parts = headers[0].split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        if not KEY_PATTERN.fullmatch(parts[1]):
            return None
        candidate = hashlib.sha256(parts[1].encode("ascii")).hexdigest()
        for known in self.key_hashes:
            if hmac.compare_digest(candidate, known):
                return known
        return None

    def _matches(self, scope: Scope) -> bool:
        headers = [
            value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"authorization"
        ]
        if len(headers) != 1:
            return False
        parts = headers[0].split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        if not KEY_PATTERN.fullmatch(parts[1]):
            return False
        candidate = hashlib.sha256(parts[1].encode("ascii")).hexdigest()
        return any(hmac.compare_digest(candidate, known) for known in self.key_hashes)
