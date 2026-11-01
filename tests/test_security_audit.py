"""Security probes written from an attacker's point of view.

Each test reproduces one concrete attack from the audit report and asserts the
hardened behaviour. Tests are written against the security requirement, never
adjusted to match the current implementation.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.settings import Settings, get_settings


def _settings(**overrides) -> Settings:
    return Settings(**{**get_settings().__dict__, "access_log_enabled": False, **overrides})


def _app(settings: Settings):
    from app.main import create_app

    return create_app(settings=settings)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000")


HEADERS = {"accept": "application/json, text/event-stream"}


# --- FINDING 1: deeply nested JSON crashed the server (RecursionError -> 500) --


@pytest.mark.asyncio
async def test_deeply_nested_json_is_rejected_not_a_500():
    """A single request must not turn a RecursionError into an HTTP 500."""
    depth = 5000
    body = b"[" * depth + b"]" * depth
    settings = _settings()
    app = _app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            response = await client.post(
                "/mcp/",
                content=body,
                headers={"content-type": "application/json", **HEADERS},
            )
    assert response.status_code == 400, response.status_code
    payload = response.json()
    assert payload["error"]["code"] in {-32700, -32600}


@pytest.mark.asyncio
async def test_excessively_nested_arrays_are_bounded_before_parsing():
    """Structural nesting is capped; brackets inside strings are not counted."""
    from app.core.mcp_transport import MAX_JSON_DEPTH, _exceeds_depth

    assert 0 < MAX_JSON_DEPTH <= 64
    assert _exceeds_depth(b"[" * (MAX_JSON_DEPTH + 1), MAX_JSON_DEPTH) is True
    # A string literal full of brackets is not nesting and must be allowed.
    assert _exceeds_depth(b'{"x": "[[[[[[[[[[[[[[[[[[[["}', MAX_JSON_DEPTH) is False

    body = b"[" * (MAX_JSON_DEPTH + 5) + b"]" * (MAX_JSON_DEPTH + 5)
    settings = _settings()
    app = _app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            response = await client.post(
                "/mcp/",
                content=body,
                headers={"content-type": "application/json", **HEADERS},
            )
    assert response.status_code == 400


# --- FINDING 2: /status leaked raw upstream API endpoints --------------------


@pytest.mark.asyncio
async def test_status_does_not_expose_upstream_api_endpoints():
    settings = _settings()
    app = _app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            response = await client.get("/status")
    assert response.status_code in {200, 401}
    assert response.status_code == 200
    blob = json.dumps(response.json())
    for endpoint in ("/api/", "api/3/action", "openfiles.", "openapi."):
        assert endpoint not in blob, f"/status leaks {endpoint!r}"


@pytest.mark.asyncio
async def test_health_tool_does_not_expose_raw_api_endpoints():
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_health", {})
    text = result.content[0].text
    for endpoint in ("/api/", "api/3/action", "openapi.izmir.bel.tr", "acikveri.bizizmir.com/api"):
        assert endpoint not in text, f"izmir_health leaks {endpoint!r}"


# --- FINDING 3: external requests followed redirects (SSRF) -------------------


def test_upstream_requests_do_not_follow_redirects():
    """A 302 from a hijacked source must not be followed to another host."""
    import inspect

    from app.connectors import http as http_module

    source = inspect.getsource(http_module)
    assert "follow_redirects=True" not in source, "redirects must not be followed blindly"


@pytest.mark.asyncio
async def test_redirect_to_another_host_is_not_followed():
    from app.connectors.http import SourceError, get_json

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    import app.connectors.http as mod

    mod.httpx.AsyncClient = patched  # type: ignore[assignment]
    try:
        with pytest.raises(SourceError):
            await get_json("https://example.test/x", timeout=2, attempts=1, max_bytes=1000)
    finally:
        mod.httpx.AsyncClient = original  # type: ignore[assignment]
    assert all("169.254" not in url for url in calls), calls


# --- FINDING 4: booleans passed numeric validation ---------------------------


def test_boolean_is_not_a_latitude():
    from app.core.validation import InputValidationError, validate_lat_lon

    with pytest.raises(InputValidationError):
        validate_lat_lon(True, 27.1)


def test_boolean_is_not_a_limit():
    from app.core.validation import InputValidationError, validate_limit

    with pytest.raises(InputValidationError):
        validate_limit(True)


def test_boolean_is_not_a_radius():
    from app.core.validation import InputValidationError, validate_radius

    with pytest.raises(InputValidationError):
        validate_radius(True)


# --- defence in depth --------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_body_is_refused_before_parsing():
    settings = _settings(client_max_body_bytes=128, mcp_max_body_bytes=128)
    app = _app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            response = await client.post(
                "/mcp/",
                content=b"{" + b" " * 4096 + b"}",
                headers={"content-type": "application/json", **HEADERS},
            )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_error_responses_never_contain_a_traceback():
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_get_dataset", {"dataset_id": "../../etc/passwd"})
    text = result.content[0].text
    for marker in ("Traceback", 'File "', "/Users/", "site-packages"):
        assert marker not in text, f"error leaks {marker!r}"


def test_no_dynamic_code_execution_in_the_codebase():
    """Belt and braces: the app must not evaluate strings as code."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app"
    forbidden = ("eval(", "exec(", "os.system(", "pickle.loads", "yaml.load(")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} uses {token}"


# --- FINDING 4b: pydantic coerced booleans before validation ------------------


@pytest.mark.asyncio
async def test_mcp_layer_rejects_boolean_coordinates():
    """`{"lat": true}` must not silently become latitude 1.0."""
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    # A boolean is refused by the input schema, so the SDK rejects the call
    # before our handler runs. Either a protocol-level ToolError or a typed
    # envelope is acceptable; silently accepting it is not.
    from mcp.server.mcpserver.exceptions import ToolError

    for tool, args in (
        ("izmir_nearby", {"lat": True, "lon": 27.1}),
        ("izmir_bus_stops", {"lat": True, "lon": 27.1}),
        ("izmir_city_services_nearby", {"lat": True, "lon": 27.1}),
        ("izmir_market_schedule", {"lat": True, "lon": 27.1}),
    ):
        try:
            result = await server.call_tool(tool, args)
        except ToolError as exc:
            assert "boolean" in str(exc).lower(), (tool, exc)
            continue
        payload = json.loads(result.content[0].text)
        assert payload["ok"] is False, f"{tool} accepted a boolean latitude"
        assert payload["error"]["field"] == "lat", (tool, payload["error"])


@pytest.mark.asyncio
async def test_outside_izmir_query_warns_that_empty_is_not_proof():
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_nearby", {"lat": 1.0, "lon": 27.1, "types": ["parking"], "radius_m": 1000})
    payload = json.loads(result.content[0].text)
    assert payload["ok"] is True
    assert payload["data"] == []
    from app.core.geo import normalize_name

    joined = normalize_name(" ".join(payload["warnings"]))
    assert "izmir" in joined and ("disinda" in joined or "outside" in joined), payload["warnings"]
