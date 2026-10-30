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
# Python's json reader is recursive; a hostile body like "[[[[...]]]]" raises
# RecursionError, which surfaced as an HTTP 500. The depth is measured before
# parsing so the failure is a clean -32700 instead of a server error.
MAX_JSON_DEPTH = 32
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


def _exceeds_depth(body: bytes, limit: int) -> bool:
    """Cheaply reject a body whose nesting exceeds ``limit``.

    Counts only structural brackets outside strings, which is enough to stop the
    recursive parser from blowing the stack; it is not a validator.
    """
    depth = 0
    in_string = False
    escaped = False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):  # [ {
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x5D, 0x7D):  # ] }
            depth -= 1
    return False


DEFAULT_MAX_BODY_BYTES = 1_000_000


class BodyTooLargeError(Exception):
    """The streamed request body exceeded the configured cap."""


class McpJsonRpcGuard:
    """ASGI middleware that validates the JSON envelope of MCP requests.

    Runs *before* auth and the rate limiter? No — the stack order in
    ``app/main.py`` puts this innermost on purpose, so a malformed body still
    consumes rate-limit budget and cannot be used to probe the server cheaply.
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") not in MCP_PATHS
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        try:
            body = await self._read_body(scope, receive, self.max_body_bytes)
        except BodyTooLargeError:
            await self._send(
                scope, receive, send, _error(INVALID_REQUEST, "Request body is too large."), 413
            )
            return
        if body is None:
            await self._send(scope, receive, send, _error(INVALID_REQUEST, "Request body is required."), 400)
            return

        if _exceeds_depth(body, MAX_JSON_DEPTH):
            await self._send(
                scope, receive, send,
                _error(PARSE_ERROR, f"JSON nesting exceeds {MAX_JSON_DEPTH} levels."),
                400,
            )
            return
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
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
    async def _read_body(
        scope: Scope, receive: Receive, max_bytes: int = DEFAULT_MAX_BODY_BYTES
    ) -> bytes | None:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > max_bytes:
                raise BodyTooLargeError
            chunks.append(chunk)
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
