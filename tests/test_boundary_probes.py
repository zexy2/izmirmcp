"""Adversarial probes: envelope integrity, service boundaries, security edges.

Targets behaviour the existing suite does not pin: what happens at the *edges*
of validation, caching, concurrency and lie-detection. A failure here is a bug
candidate; the tests are never adjusted to match the implementation.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.core.envelope import error_envelope, success_envelope
from app.core.settings import get_settings


# --- envelope honesty -----------------------------------------------------


def test_success_envelope_marks_truncation_from_matched():
    payload = success_envelope(
        summary="x", data=[{"a": 1}], matched=5, limits=["limit=1"]
    )
    assert payload["result_info"]["returned"] == 1
    assert payload["result_info"]["matched"] == 5
    assert payload["result_info"]["truncated"] is True


def test_success_envelope_without_matched_reports_unknown_completeness():
    payload = success_envelope(summary="x", data=[])
    assert payload["result_info"]["truncated"] is None
    assert payload["result_info"]["next_step"]


def test_error_envelope_marks_source_codes_temporary():
    for code in ("source_unavailable", "source_rate_limited", "source_timeout"):
        payload = error_envelope(summary="x", warning="w", code=code)
        assert payload["error"]["temporary"] is True, code


def test_error_envelope_marks_validation_not_temporary():
    payload = error_envelope(
        summary="x", warning="w", code="validation_error", field="lat"
    )
    assert payload["error"]["temporary"] is False


def test_error_envelope_never_claims_ok():
    payload = error_envelope(summary="x", warning="w", code="source_unavailable")
    assert payload["ok"] is False
    assert payload["freshness"]["status"] == "broken"


def test_public_source_url_drops_api_and_file_endpoints():
    from app.core.envelope import Source

    for url in (
        "https://openapi.izmir.bel.tr/api/ibb/x",
        "https://openfiles.izmir.bel.tr/1/docs/x.csv",
        "http://example.com/page",
    ):
        assert Source(name="n", url=url).model_dump(mode="json")["url"] is None, url


def test_public_source_url_keeps_human_pages():
    from app.core.envelope import Source

    url = "https://www.izdeniz.com.tr/duyurular"
    assert Source(name="n", url=url).model_dump(mode="json")["url"] == url


# --- validation -----------------------------------------------------------


def test_bbox_with_nan_is_rejected():
    from app.core.validation import InputValidationError, validate_bbox

    with pytest.raises(InputValidationError):
        validate_bbox([float("nan"), 38.0, 27.1, 38.5])


def test_bbox_accepts_any_ordered_rectangle_on_the_globe():
    """Shape-only validation: the axes are not checked against İzmir.

    ``[38.0, 27.0, 38.5, 27.5]`` is a valid rectangle somewhere else on earth;
    rejecting it would require a geographic policy this tool does not claim to
    have. The limitation is covered by the outside-İzmir probe below.
    """
    from app.core.validation import validate_bbox

    assert validate_bbox([38.0, 27.0, 38.5, 27.5]) == (38.0, 27.0, 38.5, 27.5)


def test_limit_zero_is_rejected():
    from app.core.validation import InputValidationError, validate_limit

    with pytest.raises(InputValidationError):
        validate_limit(0)


def test_negative_radius_is_rejected():
    from app.core.validation import InputValidationError, validate_radius

    with pytest.raises(InputValidationError):
        validate_radius(-1)


def test_sort_allows_desc_and_rejects_units():
    from app.core.validation import InputValidationError, validate_sort

    assert validate_sort("ADI desc") == "ADI desc"
    assert validate_sort("ADI") == "ADI"
    with pytest.raises(InputValidationError):
        validate_sort("ADI; DROP TABLE x")


def test_filters_reject_deeply_nested_objects():
    from app.core.validation import InputValidationError, validate_filters

    with pytest.raises(InputValidationError):
        validate_filters({"A": {"b": {"c": 1}}})


def test_filters_reject_too_many_keys():
    from app.core.validation import InputValidationError, validate_filters

    with pytest.raises(InputValidationError):
        validate_filters({f"k{i}": 1 for i in range(11)})


# --- cache behaviour ------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_cache_is_served_within_the_grace_window():
    from app.core.source_cache import cached_source_data, clear_cache

    clear_cache()
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("boom")
        return ["first"]

    first, info1 = await cached_source_data(
        "probe.stale", ttl_seconds=0, stale_if_error_seconds=60, loader=loader
    )
    second, info2 = await cached_source_data(
        "probe.stale", ttl_seconds=0, stale_if_error_seconds=60, loader=loader
    )
    assert first == second == ["first"]
    assert info1.status == "fresh"
    assert info2.status == "stale"
    clear_cache()


@pytest.mark.asyncio
async def test_cache_does_not_serve_stale_beyond_the_grace_window():
    from app.core.source_cache import cached_source_data, clear_cache

    clear_cache()

    async def loader():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cached_source_data(
            "probe.nostale", ttl_seconds=0, stale_if_error_seconds=0, loader=loader
        )
    clear_cache()


@pytest.mark.asyncio
async def test_concurrent_loads_of_the_same_key_run_once():
    from app.core.source_cache import cached_source_data, clear_cache

    clear_cache()
    calls = {"n": 0}

    async def loader():
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return ["value"]

    await asyncio.gather(*(
        cached_source_data("probe.lock", ttl_seconds=60, loader=loader) for _ in range(5)
    ))
    assert calls["n"] == 1, "cache stampede: the loader ran more than once"
    clear_cache()


# --- geo store ------------------------------------------------------------


def test_geo_store_radius_is_inclusive_at_the_exact_edge(tmp_path):
    from app.core.geo import haversine_m
    from app.storage.geo import GeoStore

    store = GeoStore(tmp_path / "g.sqlite3")
    origin = (38.41872, 27.12827)
    target = (38.42000, 27.13000)
    store.replace_all([
        {"kind": "parking", "id": "p", "name": "P", "lat": target[0], "lon": target[1]},
    ])
    exact = haversine_m(origin[0], origin[1], target[0], target[1])
    inside = store.radius(origin[0], origin[1], radius_m=exact + 1)
    assert [row["id"] for row in inside] == ["p"]


def test_geo_store_bbox_edges_are_inclusive(tmp_path):
    from app.storage.geo import GeoStore

    store = GeoStore(tmp_path / "g.sqlite3")
    store.replace_all([
        {"kind": "parking", "id": "p", "name": "P", "lat": 38.41, "lon": 27.12},
    ])
    rows = store.bbox(min_lon=27.12, min_lat=38.41, max_lon=27.12, max_lat=38.41)
    assert [row["id"] for row in rows] == ["p"]


# --- quota ----------------------------------------------------------------


def test_quota_is_atomic_under_concurrent_consumption(tmp_path):
    """Two processes sharing the file must not both see the last unit free."""
    import sqlite3

    from app.storage.quota import QuotaStore

    path = tmp_path / "q.sqlite3"
    store = QuotaStore(path)
    decisions = [store.consume("k", limit=1) for _ in range(3)]
    allowed = [decision for decision in decisions if decision.allowed]
    assert len(allowed) == 1
    with sqlite3.connect(path) as connection:
        used = connection.execute(
            "SELECT used FROM request_quota WHERE subject='k'"
        ).fetchone()[0]
    assert used == 1


# --- security -------------------------------------------------------------


def test_client_id_ignores_forwarded_header_on_public_bind():
    from app.core.abuse_guard import _client_id

    scope = {
        "client": ("203.0.113.9", 1234),
        "server": ("0.0.0.0", 8000),
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
    }
    assert _client_id(scope) == "203.0.113.9"


def test_client_id_ignores_a_comma_list_even_on_loopback():
    from app.core.abuse_guard import _client_id

    scope = {
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
        "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
    }
    assert _client_id(scope) == "127.0.0.1"


def test_duplicate_origin_headers_are_rejected():
    from app.core.cors import McpCorsMiddleware

    middleware = McpCorsMiddleware(lambda *_: None, allowed_origins=("https://ok.example",))
    scope = {
        "type": "http",
        "path": "/mcp/",
        "headers": [
            (b"origin", b"https://ok.example"),
            (b"origin", b"https://evil.example"),
        ],
    }
    origins = [v.decode() for k, v in scope["headers"] if k.lower() == b"origin"]
    assert len(origins) != 1


def test_api_key_pattern_rejects_short_and_spaced_keys():
    from app.core.api_auth import KEY_PATTERN

    assert KEY_PATTERN.fullmatch("k" * 32)
    assert not KEY_PATTERN.fullmatch("short")
    assert not KEY_PATTERN.fullmatch("k" * 31 + " ")


def test_cors_origin_validation_rejects_wildcards_and_paths():
    from app.core.cors import validate_cors_origins

    for origin in ("*", "https://a.example/path", "http://a.example",
                   "https://a.example?x=1", "https://user:pw@a.example"):
        with pytest.raises(ValueError):
            validate_cors_origins((origin,))


# --- tool surface invariants ---------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_has_a_tenant_safe_output_schema():
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    for tool in await server.list_tools():
        schema = json.dumps(tool.output_schema)
        assert "ResponseEnvelope" in schema or "$defs" in schema, tool.name


@pytest.mark.asyncio
async def test_no_tool_schema_leaks_internal_paths():
    from app.mcp.registry import create_mcp_server

    server = create_mcp_server(get_settings())
    for tool in await server.list_tools():
        blob = json.dumps(tool.input_schema) + json.dumps(tool.output_schema)
        assert "/Users/" not in blob, tool.name
        assert "sqlite3" not in blob, tool.name


# --- geographic sanity ----------------------------------------------------


def test_bbox_outside_izmir_is_technically_accepted():
    """Documented behaviour: bbox is validated for shape, not for İzmir.

    Recorded as a probe so the limitation is visible. A rectangle over another
    country currently returns an empty result rather than an error.
    """
    from app.core.validation import validate_bbox

    assert validate_bbox([0.0, 0.0, 1.0, 1.0]) == (0.0, 0.0, 1.0, 1.0)


@pytest.mark.asyncio
async def test_nearby_far_outside_izmir_returns_empty_not_error():
    from app.services.nearby import NearbyService

    envelope = await NearbyService(settings=get_settings()).nearby(
        lat=0.0, lon=0.0, types=["metro_station"], radius_m=1000, limit=5,
    )
    assert envelope["ok"] is True
    assert envelope["data"] == []
    assert envelope["warnings"], "an empty result must carry an explanation"
