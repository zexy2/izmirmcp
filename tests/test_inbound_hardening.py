from __future__ import annotations

import logging
from dataclasses import replace

import httpx
import pytest

from app.core.settings import Settings
from app.main import check_exposure, create_app

MCP_HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


def _client(app, host: str = "127.0.0.1:8000") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 5000)),
        base_url=f"http://{host}",
    )


async def _chunks(total: int, size: int = 64_000):
    sent = 0
    while sent < total:
        piece = min(size, total - sent)
        sent += piece
        yield b" " * piece


async def test_chunked_oversized_body_is_rejected_with_413():
    app = create_app(Settings(client_max_body_bytes=10_000))
    async with _client(app) as client:
        response = await client.post("/mcp/", content=_chunks(200_000), headers=MCP_HEADERS)
    assert response.status_code == 413
    assert "content-length" not in {k.lower() for k in response.request.headers}


async def test_jsonrpc_guard_caps_body_on_its_own():
    from app.core.mcp_transport import BodyTooLargeError, McpJsonRpcGuard

    messages = iter(
        [
            {"type": "http.request", "body": b"x" * 600, "more_body": True},
            {"type": "http.request", "body": b"x" * 600, "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    with pytest.raises(BodyTooLargeError):
        await McpJsonRpcGuard._read_body({}, receive, 1_000)


async def test_small_chunked_body_still_passes_the_guard():
    app = create_app(Settings(client_max_body_bytes=10_000))
    async with _client(app) as client:
        response = await client.post("/mcp/", content=_chunks(10), headers=MCP_HEADERS)
    assert response.status_code != 413


async def test_unknown_host_rejected_when_allowlist_set():
    app = create_app(Settings(mcp_allowed_hosts=("mcp.example.org",)))
    async with _client(app, host="evil.example") as client:
        assert (await client.get("/healthz")).status_code == 421
    async with _client(app, host="mcp.example.org") as client:
        assert (await client.get("/healthz")).status_code == 200


async def test_no_allowlist_keeps_backward_compatible_behaviour():
    app = create_app(Settings())
    async with _client(app, host="anything.example") as client:
        assert (await client.get("/healthz")).status_code == 200


def test_public_bind_without_keys_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="izmir_mcp.security"):
        check_exposure(Settings(host="0.0.0.0"))
    assert any("unauthenticated" in record.message for record in caplog.records)


def test_require_auth_fails_closed():
    with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
        check_exposure(Settings(host="0.0.0.0", mcp_require_auth=True))
    with pytest.raises(RuntimeError):
        check_exposure(Settings(mcp_require_auth=True))
    check_exposure(replace(Settings(host="0.0.0.0", mcp_require_auth=True), mcp_api_keys=("k" * 32,)))


def test_loopback_bind_is_quiet(caplog):
    with caplog.at_level(logging.WARNING, logger="izmir_mcp.security"):
        check_exposure(Settings())
    assert not caplog.records


def test_new_settings_read_from_env(monkeypatch):
    from app.core.settings import get_settings

    monkeypatch.setenv("IZMIR_MCP_ALLOWED_HOSTS", "a.example, b.example")
    monkeypatch.setenv("IZMIR_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setenv("IZMIR_MCP_EVENT_LOOP_WATCHDOG_SECONDS", "30")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.mcp_allowed_hosts == ("a.example", "b.example")
        assert settings.mcp_require_auth is True
        assert settings.event_loop_watchdog_seconds == 30.0
    finally:
        get_settings.cache_clear()
