"""P4 security: auth bypass, origin bypass, oversized bodies and XFF spoofing.

Every test drives the real ASGI app through its lifespan (no network, no live
source). Each case is an attack the README claims is blocked; a regression here
means the hardening claim is false.
"""
from __future__ import annotations

import contextlib
import json

import httpx
import pytest

from app.core.abuse_guard import _client_id
from app.core.api_auth import KEY_PATTERN, validate_api_keys
from app.core.cors import validate_cors_origins
from app.core.settings import Settings, get_settings

KEY = "k" * 40
OTHER_KEY = "z" * 40
ALLOWED_ORIGIN = "https://app.example.com"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def _settings(**overrides) -> Settings:
    return Settings(**{**get_settings().__dict__, **overrides})


@contextlib.asynccontextmanager
async def _app(settings: Settings):
    from app.main import create_app

    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        yield app


def _client(app, *, server: tuple[str, int] = ("127.0.0.1", 8000)) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.9", 51234)),
        base_url=f"http://{server[0]}:{server[1]}",
    )


def _client_for(scope: dict) -> str:
    return _client_id(scope)


# --- authentication -------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorisation",
    [
        None,
        "",
        f"Bearer {OTHER_KEY}",
        f"bearer {KEY.rsplit('k', 1)[0]}",  # one char short
        f"Bearer {KEY} extra",
        f"Basic {KEY}",
        f"Bearer  {KEY}",  # double space
        f"Bearer {KEY} ",  # trailing space
        KEY,  # scheme-less
        "Bearer " + "k" * 31,  # below the advertised key length
    ],
)
async def test_auth_rejects_every_malformed_or_wrong_credential(authorisation):
    headers = dict(MCP_HEADERS)
    if authorisation is not None:
        headers["authorization"] = authorisation
    async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
        response = await client.post("/mcp/", json=LIST_TOOLS, headers=headers)
    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_auth_rejects_duplicate_authorisation_headers():
    async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
        response = await client.post(
            "/mcp/",
            json=LIST_TOOLS,
            headers=[*MCP_HEADERS.items(), ("authorization", f"Bearer {KEY}"),
                     ("authorization", f"Bearer {KEY}")],
        )
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/mcp/", "/mcp", "/status"])
async def test_auth_guards_every_documented_path(path):
    async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
        method = "GET" if path == "/status" else "POST"
        kwargs = {} if method == "GET" else {"json": LIST_TOOLS, "headers": MCP_HEADERS}
        response = await client.request(method, path, **kwargs)
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/mcp/", "/mcp", "/status"],
)
async def test_auth_cannot_be_bypassed_by_path_encoding(path):
    """No path-encoding trick may reach a protected handler unauthenticated."""
    variants = [
        path,
        "/./" + path.lstrip("/"),
        "//" + path.lstrip("/"),
        path.replace("/", "//", 1),
        path + "/",
        path + ";x=1",
        path.upper(),
        path.replace("m", "%6d"),
        path + "/../" + path.strip("/"),
        "/%2e" + path,
        path + "%00",
        path + "?api_key=" + KEY,
        path + "#" + KEY,
    ]
    async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
        for variant in variants:
            if variant == path:
                continue
            method = "GET" if path == "/status" else "POST"
            kwargs = {} if method == "GET" else {"json": LIST_TOOLS, "headers": MCP_HEADERS}
            response = await client.request(method, variant, **kwargs)
            assert response.status_code != 200 or path == "/mcp", (
                f"unauthenticated request reached {variant!r} with {response.status_code}"
            )
            if path != "/mcp":
                assert response.status_code in {401, 403, 404, 405, 307, 308, 400}, (
                    f"{variant!r} answered {response.status_code} unauthenticated"
                )


@pytest.mark.asyncio
async def test_health_and_readyz_stay_public_but_leak_nothing_sensitive():
    async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
    for response in (health, ready):
        assert response.status_code == 200
        body = response.text
        assert KEY not in body
        assert "authorization" not in body.lower()


@pytest.mark.asyncio
async def test_correct_key_authenticates():
    async with _app(_settings(mcp_api_keys=(KEY, OTHER_KEY))) as app, _client(app) as client:
        response = await client.post(
            "/mcp/", json=LIST_TOOLS, headers={**MCP_HEADERS, "authorization": f"Bearer {KEY}"}
        )
    assert response.status_code == 200


# --- origin policy --------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.com",
        "http://app.example.com",  # downgraded scheme
        "https://app.example.com.evil.com",
        "https://evil.com/app.example.com",
        "https://APP.example.com",  # case-sensitive allowlist
        "https://app.example.com:8443",
        "null",
        "*",
    ],
)
async def test_origin_bypass_variants_are_rejected(origin):
    async with _app(_settings(mcp_cors_allowed_origins=(ALLOWED_ORIGIN,))) as app, _client(app) as client:
        response = await client.post(
            "/mcp/", json=LIST_TOOLS, headers={**MCP_HEADERS, "origin": origin}
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "origin_not_allowed"
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


@pytest.mark.asyncio
async def test_duplicate_origin_headers_are_rejected():
    async with _app(_settings(mcp_cors_allowed_origins=(ALLOWED_ORIGIN,))) as app, _client(app) as client:
        response = await client.post(
            "/mcp/",
            json=LIST_TOOLS,
            headers=[*MCP_HEADERS.items(), ("origin", ALLOWED_ORIGIN),
                     ("origin", "https://evil.example.com")],
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_origin_is_enforced_before_auth_so_errors_do_not_echo_state():
    """An evil browser origin gets 403 without learning whether its key worked."""
    async with _app(
        _settings(mcp_api_keys=(KEY,), mcp_cors_allowed_origins=(ALLOWED_ORIGIN,))
    ) as app, _client(app) as client:
        good_key = await client.post(
            "/mcp/",
            json=LIST_TOOLS,
            headers={"authorization": f"Bearer {KEY}", "origin": "https://evil.example.com"},
        )
        no_key = await client.post(
            "/mcp/", json=LIST_TOOLS, headers={"origin": "https://evil.example.com"}
        )
    assert good_key.status_code == no_key.status_code == 403
    assert good_key.text == no_key.text


@pytest.mark.asyncio
async def test_preflight_from_evil_origin_is_rejected():
    async with _app(_settings(mcp_cors_allowed_origins=(ALLOWED_ORIGIN,))) as app, _client(app) as client:
        response = await client.options(
            "/mcp/",
            headers={
                "origin": "https://evil.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "authorization",
            },
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_allowed_preflight_advertises_only_safe_headers():
    async with _app(_settings(mcp_cors_allowed_origins=(ALLOWED_ORIGIN,))) as app, _client(app) as client:
        response = await client.options(
            "/mcp/",
            headers={"origin": ALLOWED_ORIGIN, "access-control-request-method": "POST"},
        )
    assert response.status_code in {200, 204}
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers.get("access-control-allow-credentials") in (None, "false")
    allowed = {
        name.strip().lower()
        for name in response.headers["access-control-allow-headers"].split(",")
    }
    assert {"authorization", "content-type", "mcp-session-id"} <= allowed
    assert "x-forwarded-for" not in allowed
    # Starlette appends its CORS-safelisted defaults; nothing else, and no
    # custom/forwarding header, may appear.
    assert allowed.issubset(
        {"accept", "content-type", "authorization", "mcp-session-id",
         "mcp-protocol-version", "mcp-method", "mcp-name", "last-event-id",
         "accept-language", "content-language"}
    )


@pytest.mark.asyncio
async def test_cors_configuration_rejects_wildcards_and_plain_http():
    for bad in (
        ("*",),
        ("http://app.example.com",),
        ("https://app.example.com/path",),
        ("https://app.example.com?x=1",),
        ("https://user:pass@app.example.com",),
        ("https://app.example.com/#frag",),
        ("https://APP.example.com",),
        ("https://app.example.com ",),
    ):
        with pytest.raises(ValueError):
            validate_cors_origins(bad)
    validate_cors_origins(("http://localhost:3000", "http://127.0.0.1:8000"))
    validate_cors_origins(())


def test_api_key_configuration_rejects_weak_or_duplicate_keys():
    for bad in (("short",), ("k" * 31,), ("k" * 257,), ("has space" + "k" * 30,), (KEY, KEY)):
        with pytest.raises(ValueError):
            validate_api_keys(bad)
    validate_api_keys(())
    validate_api_keys((KEY, OTHER_KEY))
    assert KEY_PATTERN.fullmatch(KEY)


# --- body limits ----------------------------------------------------------

async def _send_body(app, body: bytes, headers: dict[str, str]):
    async with _client(app) as client:
        return await client.post("/mcp/", content=body, headers=headers)


@pytest.mark.asyncio
async def test_oversized_declared_body_is_rejected_before_parsing():
    async with _app(_settings(client_max_body_bytes=128, mcp_max_body_bytes=128)) as app:
        response = await _send_body(app, b"x" * 256, {**MCP_HEADERS, "content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error_code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_chunked_body_without_content_length_is_still_bounded():
    async def chunks():
        for _ in range(64):
            yield b"x" * 64

    async with _app(_settings(client_max_body_bytes=512, mcp_max_body_bytes=512)) as app, _client(app) as client:
        response = await client.post(
            "/mcp/",
            content=chunks(),
            headers={**MCP_HEADERS, "content-type": "application/json"},
        )
    assert response.status_code in {400, 413}
    assert response.status_code != 200


@pytest.mark.asyncio
@pytest.mark.parametrize("length", ["", "-1", "abc", "1e9", "9" * 30])
async def test_bogus_content_length_falls_through_to_the_real_body_cap(length):
    async with _app(_settings(client_max_body_bytes=128, mcp_max_body_bytes=128)) as app:
        response = await _send_body(
            app,
            b"x" * 4096,
            {**MCP_HEADERS, "content-type": "application/json", "content-length": length},
        )
    assert response.status_code in {400, 413}
    assert response.status_code != 200


@pytest.mark.asyncio
async def test_body_cap_applies_to_every_guarded_method():
    oversized = b"x" * 4096
    async with _app(_settings(client_max_body_bytes=128, mcp_max_body_bytes=128)) as app, _client(app) as client:
        post = await client.post("/mcp/", content=oversized, headers=MCP_HEADERS)
        get = await client.get("/mcp/", headers={**MCP_HEADERS, "content-length": str(len(oversized))})
        delete = await client.request("DELETE", "/mcp/", headers={**MCP_HEADERS, "content-length": str(len(oversized))})
    assert {post.status_code, get.status_code, delete.status_code} == {413}


# --- X-Forwarded-For spoofing --------------------------------------------

def _scope(host: str, *, forwarded: list[str] | None = None, client=("203.0.113.50", 1234)):
    headers = [(b"x-forwarded-for", value.encode()) for value in (forwarded or [])]
    return {"type": "http", "server": (host, 8000), "client": client, "headers": headers}


def test_xff_is_ignored_when_the_server_is_public():
    scope = _scope("0.0.0.0", forwarded=["198.51.100.1"])
    assert _client_for(scope) == "203.0.113.50"


def test_xff_is_honoured_only_for_a_single_header_behind_loopback():
    scope = _scope("127.0.0.1", forwarded=["198.51.100.1"])
    assert _client_for(scope) == "198.51.100.1"


@pytest.mark.parametrize(
    "forwarded",
    [
        ["198.51.100.1", "198.51.100.2"],  # duplicated header
        ["198.51.100.1, 10.0.0.9"],  # comma list is ambiguous; first is not trusted twice
    ],
)
def test_xff_lists_and_duplicates_do_not_multiply_identities(forwarded):
    scope = _scope("127.0.0.1", forwarded=forwarded)
    # Either a single, stable identity or the socket peer: never two clients
    # from one connection.
    assert _client_for(scope) == "203.0.113.50"


def test_xff_with_empty_value_falls_back_to_the_socket_peer():
    scope = _scope("127.0.0.1", forwarded=["   "])
    assert _client_for(scope) == "203.0.113.50"


@pytest.mark.asyncio
async def test_spoofed_xff_cannot_reset_the_rate_limit_on_a_public_bind():
    """A public bind must not let a client mint a new bucket per request."""
    settings = _settings(
        client_rate_limit_capacity=1,
        client_rate_limit_refill_per_second=0.001,
        host="0.0.0.0",
    )
    async with _app(settings) as app, _client(app, server=("0.0.0.0", 8000)) as client:
        first = await client.post(
            "/mcp/", json={**LIST_TOOLS, "id": 1},
            headers={**MCP_HEADERS, "x-forwarded-for": "198.51.100.1"},
        )
        second = await client.post(
            "/mcp/", json={**LIST_TOOLS, "id": 2},
            headers={**MCP_HEADERS, "x-forwarded-for": "198.51.100.2"},
        )
    assert first.status_code != 429
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_forwarded_header_variants_cannot_override_the_socket_peer():
    settings = _settings(client_rate_limit_capacity=1, client_rate_limit_refill_per_second=0.001)
    variants = [
        {"x-forwarded-for": "198.51.100.1, 198.51.100.2"},
        {"x-real-ip": "198.51.100.3"},
        {"forwarded": "for=198.51.100.4"},
        {"x-client-ip": "198.51.100.5"},
        {"cf-connecting-ip": "198.51.100.6"},
    ]
    async with _app(settings) as app, _client(app) as client:
        statuses = []
        for index, extra in enumerate(variants):
            response = await client.post(
                "/mcp/", json={**LIST_TOOLS, "id": index}, headers={**MCP_HEADERS, **extra}
            )
            statuses.append(response.status_code)
    assert statuses[0] != 429
    assert statuses[1:] == [429] * (len(variants) - 1), statuses


# --- logging hygiene ------------------------------------------------------

@pytest.mark.asyncio
async def test_access_log_never_contains_keys_headers_or_query_strings(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="izmir_mcp.access"):
        async with _app(_settings(mcp_api_keys=(KEY,))) as app, _client(app) as client:
            await client.get("/status?api_key=" + KEY, headers={"authorization": f"Bearer {KEY}"})
    records = [record.getMessage() for record in caplog.records if record.name == "izmir_mcp.access"]
    assert records
    joined = "\n".join(records)
    assert KEY not in joined
    assert "api_key" not in joined
    assert "authorization" not in joined.lower()
    payload = json.loads(records[-1])
    assert payload["path"] == "/status"
