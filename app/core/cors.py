"""Origin allowlist and CORS headers for the MCP endpoint.

The endpoint is open by default (no ``Origin`` header, e.g. CLI MCP clients).
When a browser sends an ``Origin``, it must appear in the explicit allowlist;
there is no wildcard, so a misconfigured deployment fails closed instead of
silently allowing every site to call the server.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

ALLOW_METHODS = ("GET", "POST", "DELETE", "OPTIONS")
ALLOW_HEADERS = (
    "Accept",
    "Content-Type",
    "Authorization",
    "Mcp-Session-Id",
    "Mcp-Protocol-Version",
    "Mcp-Method",
    "Mcp-Name",
    "Last-Event-ID",
)
EXPOSE_HEADERS = (
    "Mcp-Session-Id",
    "Mcp-Protocol-Version",
    "WWW-Authenticate",
    "Retry-After",
)
MCP_PATHS = {"/mcp", "/mcp/"}
MAX_AGE_SECONDS = 600
HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")


def validate_cors_origins(origins: tuple[str, ...]) -> None:
    error = (
        "IZMIR_MCP_CORS_ALLOWED_ORIGINS requires at most 32 unique HTTPS origins; "
        "HTTP is allowed only for localhost, 127.0.0.1 or [::1]. No wildcard, "
        "credentials, path, query or fragment."
    )
    if len(origins) > 32 or len(set(origins)) != len(origins):
        raise ValueError(error)
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            host, port = parsed.hostname, parsed.port
            valid = (
                0 < len(origin) <= 2048
                and origin.isascii()
                and host is not None
                and len(host) <= 253
                and (host == "::1" or HOST_PATTERN.fullmatch(host) is not None)
                and (port is None or 1 <= port <= 65535)
                and (
                    parsed.scheme == "https" or (parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"})
                )
                and parsed.username is None
                and parsed.password is None
                and origin == f"{parsed.scheme}://{parsed.netloc}"
                and parsed.netloc == parsed.netloc.lower()
                and not any(char.isspace() for char in origin)
                and not any(char in origin for char in "*\\%")
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            # A misconfigured value can contain a password; never echo it.
            raise ValueError(error)


class McpCorsMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: tuple[str, ...]):
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        self.cors = CORSMiddleware(
            self._dispatch,
            allow_origins=list(allowed_origins),
            allow_methods=ALLOW_METHODS,
            allow_headers=ALLOW_HEADERS,
            expose_headers=EXPOSE_HEADERS,
            allow_credentials=False,
            max_age=MAX_AGE_SECONDS,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in MCP_PATHS:
            await self.app(scope, receive, send)
            return
        origins = [value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"origin"]
        if origins and (len(origins) != 1 or origins[0] not in self.allowed_origins):
            response = JSONResponse(
                {
                    "ok": False,
                    "error_code": "origin_not_allowed",
                    "summary": "This browser origin is not allowed.",
                },
                status_code=403,
                headers={"Vary": "Origin", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.cors(scope, receive, send)

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") == "OPTIONS":
            response = Response(
                status_code=204,
                headers={"Allow": "GET, POST, DELETE, OPTIONS", "Vary": "Origin"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
