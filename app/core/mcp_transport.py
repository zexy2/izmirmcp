"""Reject malformed JSON-RPC before it reaches the MCP SDK.

The SDK answers a broken request with a generic error that surfaces as an
internal-looking failure. Catching it here produces a protocol-correct
``-32600``/``-32700`` response and keeps SDK internals out of the message.

Only the envelope is validated; tool arguments are the SDK's job.
"""
from __future__ import annotations

import json

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MCP_PATHS = {"/mcp", "/mcp/"}
MAX_ID_LENGTH = 128
PARSE_ERROR = -32700
INVALID_REQUEST = -32600


def _error(code: int, message: str, *, request_id: object = None) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def validate_message(payload: object) -> tuple[bool, str | None, object]:
    """Return ``(ok, problem, request_id)`` for one parsed JSON-RPC message.

    Notifications (no ``id``) are allowed and are not validated further here:
    the only notification the SDK requires is ``notifications/initialized``.
    """
    if not isinstance(payload, dict):
        return False, "a JSON-RPC message must be an object", None

    request_id = payload.get("id")
    if request_id is not None:
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            return False, "id must be a string or an integer", None
        if isinstance(request_id, str) and len(request_id) > MAX_ID_LENGTH:
            return False, "id is too long", None

    if payload.get("jsonrpc") != "2.0":
        return False, 'jsonrpc must be exactly "2.0"', request_id

    method = payload.get("method")
    if method is None:
        # A response (result/error) travelling client-to-server is invalid.
        return False, "method is required", request_id
    if not isinstance(method, str) or not method.strip():
        return False, "method must be a non-empty string", request_id
    if len(method) > 200:
        return False, "method is too long", request_id

    params = payload.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        return False, "params must be an object or an array", request_id

    return True, None, request_id


class McpJsonRpcGuard:
    """ASGI middleware that validates the JSON envelope of MCP requests.

    Runs *before* auth and the rate limiter? No — the stack order in
    ``app/main.py`` puts this innermost on purpose, so a malformed body still
    consumes rate-limit budget and cannot be used to probe the server cheaply.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") not in MCP_PATHS
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        body = await self._read_body(scope, receive)
        if body is None:
            await self._send(scope, receive, send, _error(INVALID_REQUEST, "Request body is required."), 400)
            return

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._send(scope, receive, send, _error(PARSE_ERROR, "Invalid JSON."), 400)
            return

        messages = payload if isinstance(payload, list) else [payload]
        if isinstance(payload, list) and not messages:
            await self._send(scope, receive, send, _error(INVALID_REQUEST, "Empty batch."), 400)
            return

        for message in messages:
            ok, problem, request_id = validate_message(message)
            if not ok:
                await self._send(
                    scope, receive, send,
                    _error(INVALID_REQUEST, problem or "Invalid request.", request_id=request_id),
                    400,
                )
                return

        await self.app(scope, self._replay(receive, body), send)

    @staticmethod
    async def _read_body(scope: Scope, receive: Receive) -> bytes | None:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        return body or None

    @staticmethod
    def _replay(receive: Receive, body: bytes) -> Receive:
        """Feed the already-read body to the inner app exactly once."""
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return replay

    async def _send(
        self, scope: Scope, receive: Receive, send: Send, payload: dict, status: int
    ) -> None:
        response = JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)
