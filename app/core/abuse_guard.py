"""Body-size, per-client rate and concurrency guards for the MCP endpoint."""
from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.rate_limit import ClientRateLimiter, ConcurrencyLimiter

PROTECTED_PATHS = ("/mcp", "/mcp/")
GUARDED_METHODS = ("GET", "POST", "DELETE")


def _client_id(scope: Scope) -> str:
    """Identify a caller without trusting spoofable proxy headers.

    ``X-Forwarded-For`` is only honoured when the server is bound to a loopback
    host, where a local reverse proxy is the expected deployment.
    """
    server = scope.get("server")
    host = server[0] if server else ""
    forwarded = [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == b"x-forwarded-for"
    ]
    if host in {"127.0.0.1", "localhost", "::1"} and len(forwarded) == 1:
        first = forwarded[0].split(",")[0].strip()
        if first:
            return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class McpAbuseGuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        rate_limiter: ClientRateLimiter,
        concurrency_limiter: ConcurrencyLimiter,
    ):
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))
        self.rate_limiter = rate_limiter
        self.concurrency_limiter = concurrency_limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in PROTECTED_PATHS:
            await self.app(scope, receive, send)
            return
        if scope.get("method") not in GUARDED_METHODS:
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            await self._reject(
                scope, receive, send, 413, "payload_too_large",
                "Request body exceeds the advertised limit.",
            )
            return

        allowed, retry_after = await self.rate_limiter.acquire(_client_id(scope))
        if not allowed:
            await self._reject(
                scope, receive, send, 429, "rate_limited",
                "Too many requests from this client.",
                headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
            )
            return

        if not await self.concurrency_limiter.acquire():
            await self._reject(
                scope, receive, send, 503, "server_busy",
                "Too many concurrent requests.",
                headers={"Retry-After": "1"},
            )
            return
        try:
            await self.app(scope, receive, send)
        finally:
            await self.concurrency_limiter.release()

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        error_code: str,
        summary: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        response = JSONResponse(
            {"ok": False, "error_code": error_code, "summary": summary},
            status_code=status_code,
            headers={"Cache-Control": "no-store", **(headers or {})},
        )
        await response(scope, receive, send)
