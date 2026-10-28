"""One structured JSON line per HTTP request.

Logs method, path, status and duration. Query strings, bodies, headers and API
keys are never logged, so a shared log cannot leak caller content or credentials.
"""
from __future__ import annotations

import json
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("izmir_mcp.access")


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp, *, enabled: bool = True):
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "method": scope.get("method"),
                        "path": scope.get("path"),
                        "status": status_code,
                        "duration_ms": elapsed_ms,
                    },
                    ensure_ascii=False,
                )
            )
