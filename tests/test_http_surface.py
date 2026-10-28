from __future__ import annotations

import contextlib
import json

import httpx
import pytest

from app.core.settings import Settings, get_settings


def _settings(**overrides) -> Settings:
    base = get_settings()
    return Settings(**{**base.__dict__, **overrides})


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
    )


def _app(settings: Settings):
    from app.main import create_app

    return create_app(settings=settings)


@contextlib.asynccontextmanager
async def _running_app(settings: Settings):
    """Run the real lifespan so the MCP session manager is initialised."""
    app = _app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.mark.asyncio
async def test_healthz_reports_ok():
    async with _running_app(_settings()) as app, _client(app) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_readyz_reports_local_readiness_not_upstream_health():
    async with _running_app(_settings()) as app, _client(app) as client:
        response = await client.get("/readyz")
    payload = response.json()
    assert response.status_code == 200
    assert payload["ready"] is True
    assert payload["upstream_health"] == "not_checked"
    assert payload["checks"]["tool_surface"] == "ok"


@pytest.mark.asyncio
async def test_status_includes_rate_limit_and_concurrency_telemetry():
    async with _running_app(_settings()) as app, _client(app) as client:
        response = await client.get("/status")
    payload = response.json()
    assert payload["tool_count"] == len(payload["tools"])
    assert "rate_limit" in payload
    assert "concurrency" in payload
    assert payload["rate_limit"]["capacity"] >= 1


@pytest.mark.asyncio
async def test_mcp_path_rejects_oversized_body():
    settings = _settings(mcp_max_body_bytes=64, client_max_body_bytes=64)
    async with _running_app(settings) as app, _client(app) as client:
        response = await client.post(
            "/mcp/",
            content=b"x" * 500,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error_code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_mcp_path_rate_limits_per_client():
    settings = _settings(client_rate_limit_capacity=1, client_rate_limit_refill_per_second=0.001)
    async with _running_app(settings) as app, _client(app) as client:
        first = await client.post(
            "/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
        second = await client.post(
            "/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    assert second.status_code == 429
    assert second.json()["error_code"] == "rate_limited"
    assert "retry-after" in {key.lower() for key in second.headers}
    assert first.status_code != 429


@pytest.mark.asyncio
async def test_cors_allows_configured_origin_and_rejects_others():
    settings = _settings(mcp_cors_allowed_origins=("https://app.example.com",))
    async with _running_app(settings) as app, _client(app) as client:
        allowed = await client.options(
            "/mcp/",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
            },
        )
        blocked = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "origin": "https://evil.example.com",
                "accept": "application/json, text/event-stream",
            },
        )
    assert allowed.status_code in {200, 204}
    assert allowed.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "origin_not_allowed"


@pytest.mark.asyncio
async def test_no_origin_header_is_not_blocked():
    async with _running_app(_settings()) as app, _client(app) as client:
        response = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    assert response.status_code not in {403, 429, 413}


@pytest.mark.asyncio
async def test_auth_is_off_by_default_and_on_when_keys_are_configured():
    key = "a" * 40
    open_settings = _settings()
    auth_settings = _settings(mcp_api_keys=(key,))
    async with _running_app(open_settings) as app, _client(app) as client:
        anonymous = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
    async with _running_app(auth_settings) as app, _client(app) as client:
        missing = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"accept": "application/json, text/event-stream"},
        )
        wrong = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "accept": "application/json, text/event-stream",
                "authorization": "Bearer " + "b" * 40,
            },
        )
        correct = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "accept": "application/json, text/event-stream",
                "authorization": f"Bearer {key}",
            },
        )
    assert anonymous.status_code not in {401, 403}
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert missing.headers.get("www-authenticate", "").startswith("Bearer")


@pytest.mark.asyncio
async def test_healthz_and_readyz_stay_open_under_auth():
    key = "c" * 40
    async with _running_app(_settings(mcp_api_keys=(key,))) as app, _client(app) as client:
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
        status = await client.get("/status")
    assert health.status_code == 200
    assert ready.status_code == 200
    assert status.status_code == 401


@pytest.mark.asyncio
async def test_structured_json_log_line_is_emitted(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="izmir_mcp.access"):
        async with _running_app(_settings()) as app, _client(app) as client:
            await client.get("/healthz")
    records = [r for r in caplog.records if r.name == "izmir_mcp.access"]
    assert records, "expected an access log record"
    payload = json.loads(records[-1].getMessage())
    assert payload["event"] == "http_request"
    assert payload["path"] == "/healthz"
    assert payload["status"] == 200
    assert "duration_ms" in payload


@pytest.mark.asyncio
async def test_readyz_reports_local_checks_and_hides_details(tmp_path):
    settings = _settings(database_path=str(tmp_path / "db.sqlite3"))
    async with _running_app(settings) as app, _client(app) as client:
        response = await client.get("/readyz")
    payload = response.json()
    assert response.status_code == 200
    assert payload["ready"] is True
    assert payload["checks"]["timetable_store"] == "absent"
    assert payload["checks"]["tool_surface"] == "ok"
    assert str(tmp_path) not in str(payload)


@pytest.mark.asyncio
async def test_readyz_is_503_when_the_store_is_corrupt(tmp_path):
    (tmp_path / "db.sqlite3").write_bytes(b"garbage")
    settings = _settings(database_path=str(tmp_path / "db.sqlite3"))
    async with _running_app(settings) as app, _client(app) as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["ready"] is False


@pytest.mark.asyncio
async def test_status_exposes_tool_telemetry_after_a_call():
    from app.core.tool_telemetry import reset_tool_telemetry

    reset_tool_telemetry()
    async with _running_app(_settings()) as app, _client(app) as client:
        await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "izmir_health", "arguments": {}}},
            headers={"accept": "application/json, text/event-stream"},
        )
        response = await client.get("/status")
    payload = response.json()
    assert "tools_telemetry" in payload
    assert payload["tools_telemetry"]["izmir_health"]["calls"] >= 1
