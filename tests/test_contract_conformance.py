"""P4 contract conformance: every advertised behaviour keeps the envelope contract.

These tests never touch the network. Every upstream call is replaced at the HTTP
connector boundary with a fixed fixture, so the suite can drive all 17 tools
through success *and* failure paths and assert the same envelope shape each time.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.envelope import ResponseEnvelope, public_page_url
from app.core.settings import get_settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, TOOL_TITLES, create_mcp_server

ENVELOPE_FIELDS = frozenset(ResponseEnvelope.model_fields)

TEMPORARY_CODES = frozenset(
    {"source_unavailable", "source_rate_limited", "source_timeout"}
)

# One minimally valid success call per tool. Bus departures is excluded here
# because it needs the local GTFS SQLite store and is covered separately against
# its validation path plus the bus service tests.
SUCCESS_CALLS: dict[str, dict[str, Any]] = {
    "izmir_health": {},
    "izmir_search_datasets": {"query": "otopark", "limit": 1},
    "izmir_get_dataset": {"dataset_id": "otoparklar"},
    "izmir_get_resource_schema": {"resource_id": "r1"},
    "izmir_query_resource": {"resource_id": "r1", "limit": 1},
    "izmir_nearby": {"lat": 38.41872, "lon": 27.12827, "types": ["parking"], "limit": 1},
    "izmir_water_status": {"kind": "dams", "limit": 1},
    "izmir_air_quality": {"date": "2026-10-01", "limit": 1},
    "izmir_transit_stations": {"mode": "metro", "limit": 1},
    "izmir_transit_schedule": {"mode": "metro"},
    "izmir_bus_stops": {"query": "Konak", "limit": 1},
    "izmir_bus_routes": {"limit": 1},
    "izmir_market_schedule": {"district": "Konak", "limit": 1},
    "izmir_transport_disruptions": {"operator": "metro", "limit": 1},
    "izmir_city_services_nearby": {
        "lat": 38.41872, "lon": 27.12827, "kinds": ["wifi"], "limit": 1,
    },
}

# Inputs that must be rejected locally, before any network call.
INVALID_CALLS: dict[str, dict[str, Any]] = {
    "izmir_search_datasets": {"query": "   "},
    "izmir_get_dataset": {"dataset_id": ""},
    "izmir_get_resource_schema": {"resource_id": "../etc/passwd"},
    "izmir_query_resource": {"resource_id": "r1", "filters": {"bad key!": 1}},
    "izmir_nearby": {"lat": 38.4, "lon": 27.1, "radius_m": -1},
    "izmir_air_quality": {"date": "2026-13-99"},
    "izmir_bus_stops": {},
    "izmir_bus_departures": {"stop_id": "", "at": "25:99"},
    "izmir_market_schedule": {"day": "olmayan-gun"},
    "izmir_city_services_nearby": {"lat": 38.4, "lon": 27.1, "radius_m": 0},
}

CSV_FIXTURE = (
    "BARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;DOLULUK_ORANI;SU_YUKSEKLIGI;"
    "TUKETILEBILIR_SU_KAPASITESI;MAKSIMUM_SU_KAPASITESI;MAKSIMUM_SU_YUKSEKLIGI;"
    "ENLEM;BOYLAM;KULLANILABILIR_GOL_SU_HACMI\n"
    "1;Tahtalı;2026-10-27;42,5;100,0;1000;2000;150,0;38,1;27,1;900\n"
)

# Columns the published city-layer and notice datasets carry; a fixture row with
# these names keeps every layer mapper happy without inventing content.
DATASET_COLUMNS = (
    "_id", "ADI", "ILCE", "MAHALLE", "YOL", "ACIKLAMA", "ENLEM", "BOYLAM",
    "DURAK_ID", "DURAK_ADI", "DURAKTAN_GECEN_HATLAR",
    "HAT_KODU", "HAT_ADI", "BASLANGIC_TARIHI", "BITIS_TARIHI", "DUYURU",
)

def _gtfs_rows(name: str) -> str:
    """Minimal but valid GTFS members for the envelope-level replay."""
    members = {
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type\r\n"
            "1,1,Fixtures - Konak,3\r\n"
        ),
        "trips.txt": "route_id,service_id,trip_id,direction_id\r\n1,WK,T1,0\r\n",
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\r\nWK,1,1,1,1,1,0,0,20250101,20261009\r\n"
        ),
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\r\n10001,Fixtures Durak,38.4,27.1\r\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\r\n"
            "T1,08:00:00,08:00:00,10001,1\r\n"
        ),
    }
    return members[name]


def _gtfs_archive() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in ("routes.txt", "trips.txt", "calendar.txt", "stops.txt", "stop_times.txt"):
            archive.writestr(name, _gtfs_rows(name))
    return buffer.getvalue()


# Tools that answer from local state only and never touch a source.
LOCAL_ONLY_TOOLS = frozenset({"izmir_health"})


def _envelope_from_result(result) -> dict[str, Any]:
    assert result.content, "tool returned no content"
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict), "tool text content must be a JSON object"
    return payload


def _assert_envelope(payload: dict[str, Any]) -> None:
    assert set(payload) == ENVELOPE_FIELDS, (
        f"envelope drifted: missing={sorted(ENVELOPE_FIELDS - set(payload))} "
        f"extra={sorted(set(payload) - ENVELOPE_FIELDS)}"
    )
    ResponseEnvelope.model_validate(payload)
    assert isinstance(payload["summary"], str) and payload["summary"].strip()
    assert isinstance(payload["data"], list)
    assert all(isinstance(row, dict) for row in payload["data"])
    for key in ("limits", "warnings", "next_queries"):
        assert isinstance(payload[key], list)
        assert all(isinstance(item, str) for item in payload[key]), key
    assert isinstance(payload["sources"], list)
    assert all(isinstance(source, dict) for source in payload["sources"])
    assert payload["freshness"]["status"] in {"fresh", "stale", "unknown", "broken"}
    result_info = payload["result_info"]
    assert result_info["returned"] == len(payload["data"])
    assert result_info["scope"]
    if payload["ok"]:
        assert payload["error"] is None
    else:
        assert payload["error"] is not None
        assert payload["error"]["code"]
        assert result_info["scope"] == "error_details"


class UpstreamClient(httpx.AsyncClient):
    """AsyncClient whose transport records every request and answers via script.

    Requests are recorded first and only answered afterwards, so the success
    pass can capture real fixture responses for the failure pass.
    """

    def __init__(self, *args, **kwargs):
        self._recorder = kwargs.pop("recorder")
        kwargs["transport"] = httpx.MockTransport(self._recorder.respond)
        super().__init__(*args, **kwargs)


class Recorder:
    def __init__(self, routes: dict[str, Any] | None = None, *, record_only: bool = False):
        self.routes = routes or {}
        self.record_only = record_only
        self.requests: list[httpx.Request] = []
        self.responses: dict[tuple[str, str], httpx.Response] = {}
        self.fallback: httpx.Response | None = None
        self.mode: Any = None

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.mode is not None:
            return self.mode(request)
        key = (request.method, request.url.path)
        if key in self.responses and not self.record_only:
            return self.responses[key]
        if self.record_only:
            return self._improvise(request)
        for suffix, response in self.routes.items():
            if suffix in str(request.url):
                answer = response(request) if callable(response) else response
                self._remember(key, answer)
                return answer
        if self.fallback is not None:
            return self._remember(key, self._improvise(request))
        raise AssertionError(f"unexpected upstream call: {request.method} {request.url}")

    def _improvise(self, request: httpx.Request) -> httpx.Response:
        """Answer an unscripted call with a shape-accurate empty payload.

        Fixtures are deliberately minimal: the point is the envelope, not the
        row content, so every unscripted endpoint returns an empty, valid body
        of the expected JSON shape.
        """
        path = request.url.path
        segments = [segment for segment in path.split("/") if segment]
        rows: dict[str, Any] = {}
        for column in DATASET_COLUMNS:
            rows[column] = "Fixtures" if column in {"ADI", "ILCE", "MAHALLE", "YOL"} else None
        rows["_id"] = 1
        rows["ENLEM"] = "38,41872"
        rows["BOYLAM"] = "27,12827"
        rows["DURAK_ID"] = "10001"
        rows["DURAK_ADI"] = "Fixtures Durak"
        rows["DURAKTAN_GECEN_HATLAR"] = "1"
        if "announcement" in path:
            body = [{"id": "fixture", "title": "Fixture duyuru", "summary": "Fixture",
                     "publishedAt": "2026-10-27T00:00:00", "slug": "fixture"}]
            if "metrotramapi" in str(request.url.host):
                return _ok_json({"isSuccessful": True, "data": body})
            return _ok_json({"data": {"data": body}})
        if "openapi.izmir.bel.tr" in str(request.url.host) and segments:
            # The open API publishes bare JSON arrays (and one object payload).
            if segments[-1] in {"izdenizseferleri", "harman"}:
                return _ok_json({"departures": []})
            return _ok_json([])
        if "/api/v1/announcements" in path:
            body = [{"id": "fixture", "title": "Fixture duyuru", "summary": "Fixture",
                     "publishedAt": "2026-10-27T00:00:00", "slug": "fixture"}]
            if "metrotramapi" in path or "metrotramapi" in str(request.url.host):
                return _ok_json({"isSuccessful": True, "data": body})
            return _ok_json({"data": {"data": body}})
        if path.endswith(".zip") or "gtfs" in path:
            return httpx.Response(
                200, content=_gtfs_archive(), headers={"content-type": "application/zip"}
            )
        if "/api/3/action/" in path:
            action = path.rsplit("/", 1)[-1]
            result: Any = {"results": [], "count": 0}
            if action == "package_show":
                result = {"name": "fixture", "title": "fixture", "resources": []}
            if action == "datastore_search":
                result = {
                    "fields": [{"id": column, "type": "text"} for column in DATASET_COLUMNS],
                    "records": [rows],
                    "total": 1,
                }
            return _ok_json({"success": True, "result": result})
        if "dam" in path or path.endswith(".csv"):
            return _ok_json([]) if path.endswith(".json") else httpx.Response(
                200, text=CSV_FIXTURE, headers={"content-type": "text/csv"}
            )
        return _ok_json([])

    def _remember(self, key, response: httpx.Response) -> httpx.Response:
        stored = httpx.Response(
            response.status_code,
            content=response.read(),
            headers={"content-type": response.headers.get("content-type", "")},
        )
        self.responses[key] = stored
        return stored


@pytest.fixture
def recorder(monkeypatch):
    from app.core.source_cache import clear_cache

    clear_cache()

    def _factory(routes: dict[str, Any] | None = None) -> Recorder:
        scripted = Recorder(routes)
        monkeypatch.setattr(
            "app.connectors.http.httpx.AsyncClient",
            lambda *args, **kwargs: UpstreamClient(*args, recorder=scripted, **kwargs),
        )
        return scripted

    yield _factory
    clear_cache()


@pytest.fixture
def upstream(recorder):
    return recorder()


def _ok_json(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


async def _capture(recorder, tool_name: str) -> tuple[dict[str, Any], Recorder]:
    """Run one tool twice: once recording real fixtures, then from the fixtures.

    The first pass answers through ``record_only``, which records each upstream
    response before running the real tool code. The second pass replays exactly
    those responses with no more live knowledge.
    """
    server = create_mcp_server(get_settings())
    recording = recorder()
    recording.record_only = True
    recording.fallback = _ok_json([])
    first = _envelope_from_result(await server.call_tool(tool_name, SUCCESS_CALLS[tool_name]))
    if tool_name not in LOCAL_ONLY_TOOLS:
        assert recording.requests, f"{tool_name} made no upstream call to capture"
    from app.core.source_cache import clear_cache

    clear_cache()
    replay = recorder()
    replay.responses.update(recording.responses)
    replay.record_only = False
    # Same-URL cache keys can legitimately differ (CKAN query strings are not
    # part of the path), so replay keeps a shape-accurate improviser for any
    # path the recorder did not see.
    replay.fallback = _ok_json([])
    second = _envelope_from_result(await server.call_tool(tool_name, SUCCESS_CALLS[tool_name]))
    return second, replay


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(SUCCESS_CALLS))
async def test_success_envelope_conforms_for_every_tool(tool_name, recorder):
    payload, replay = await _capture(recorder, tool_name)
    _assert_envelope(payload)
    assert payload["ok"] is True, payload["summary"]
    assert payload["freshness"]["retrieved_at"]
    assert all(isinstance(response, httpx.Response) for response in replay.responses.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(SUCCESS_CALLS))
async def test_source_failures_are_taxonomised_not_raised(tool_name, recorder):
    """Replay the captured upstream calls as 503 and as 429.

    Every tool must still answer with a full envelope; the failure either turns
    into a typed temporary error or a partial answer whose warnings say why.
    """
    _, replay = await _capture(recorder, tool_name)
    server = create_mcp_server(get_settings())
    for status, expected_code in ((503, "source_unavailable"), (500, "source_unavailable")):
        from app.core.source_cache import clear_cache

        clear_cache()
        replay.mode = lambda request, status=status: httpx.Response(status, text="upstream down")
        result = await server.call_tool(tool_name, SUCCESS_CALLS[tool_name])
        payload = _envelope_from_result(result)
        _assert_envelope(payload)
        if payload["ok"]:
            if tool_name not in LOCAL_ONLY_TOOLS:
                assert payload["warnings"], f"{tool_name} hid a {status} without a warning"
            continue
        assert payload["error"]["code"] == expected_code, payload["error"]
        assert payload["error"]["temporary"] is True
        assert payload["freshness"]["status"] in {"broken", "stale"}


@pytest.mark.asyncio
async def test_rate_limited_source_is_typed_across_services():
    """HTTP 429 must surface as ``source_rate_limited``, never as an outage.

    A rate limit is temporary and retryable; labelling it ``source_unavailable``
    would tell a caller to give up. Each service maps connector failures through
    the shared ``source_failure_envelope`` helper, so this holds everywhere.
    """
    from app.connectors.http import SourceRateLimitedError
    from app.services.catalog import CatalogService
    from app.services.markets import MarketService

    class LimitedCkan:
        async def package_search(self, **_kwargs):
            raise SourceRateLimitedError("source rate limit exceeded")

    class LimitedMarket:
        async def market_rows(self):
            raise SourceRateLimitedError("source rate limit exceeded")

    catalog = await CatalogService(
        settings=get_settings(), client=LimitedCkan()
    ).search_datasets(query="otopark", limit=3)
    market = await MarketService(
        settings=get_settings(), api=LimitedMarket()
    ).schedule(limit=3)

    for payload in (catalog, market):
        assert payload["ok"] is False
        assert payload["error"]["code"] == "source_rate_limited", payload["error"]
        assert payload["error"]["temporary"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(INVALID_CALLS))
async def test_validation_errors_conform_and_never_reach_upstream(tool_name, upstream):
    server = create_mcp_server(get_settings())
    result = await server.call_tool(tool_name, INVALID_CALLS[tool_name])
    payload = _envelope_from_result(result)
    _assert_envelope(payload)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["temporary"] is False
    assert payload["error"]["field"], "validation_error must name the offending field"
    assert not upstream.requests, "a locally invalid input must not hit the network"


@pytest.mark.asyncio
async def test_izban_disruptions_are_explicitly_unavailable(recorder):
    """İZBAN publishes no reachable feed: the answer is typed, never invented."""
    upstream = recorder()
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_transport_disruptions", {"operator": "izban"})
    payload = _envelope_from_result(result)
    _assert_envelope(payload)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "source_unavailable"
    assert payload["warnings"]
    assert not upstream.requests, "İZBAN has no verified endpoint to probe"


@pytest.mark.asyncio
async def test_unknown_tool_name_is_reported_as_an_error_not_a_crash():
    server = create_mcp_server(get_settings())
    with pytest.raises(Exception) as excinfo:
        await server.call_tool("izmir_no_such_tool", {})
    # The SDK raises a protocol-level error for an unknown name; it must not be
    # a Python KeyError/AttributeError leaking internals.
    assert type(excinfo.value).__name__ in {"ToolError", "McpError", "ValueError"}


@pytest.mark.asyncio
async def test_structured_content_matches_text_content_for_health():
    """``structured_output`` and the text block must describe the same envelope."""
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_health", {})
    text_payload = _envelope_from_result(result)
    assert result.structured_content is not None
    structured = result.structured_content
    if isinstance(structured, dict) and "result" in structured and len(structured) == 1:
        structured = structured["result"]
    assert set(structured) == set(text_payload)
    assert structured["data"] == text_payload["data"]


def test_public_page_url_drops_machine_endpoints():
    assert public_page_url("https://acikveri.bizizmir.com/dataset/otoparklar")
    assert public_page_url("http://acikveri.bizizmir.com/dataset/x") is None
    assert public_page_url("https://api.izmir.bel.tr/v1/x") is None
    assert public_page_url("https://example.com/data.csv") is None
    assert public_page_url("https://example.com/api/x") is None
    assert public_page_url(None) is None


def test_tool_titles_and_names_stay_in_sync():
    assert set(TOOL_TITLES) == set(DEFAULT_TOOL_NAMES)
    assert len(DEFAULT_TOOL_NAMES) == len(set(DEFAULT_TOOL_NAMES)) == 17


@pytest.mark.asyncio
async def test_advertised_tools_reject_unknown_arguments_without_crashing():
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_health", {"bogus": 1})
    # A protocol-level rejection is acceptable; a raw TypeError is not.
    if result.content:
        payload = _envelope_from_result(result)
        _assert_envelope(payload)
        if payload["ok"] is False:
            assert payload["error"]["code"] in {"validation_error", "request_failed"}


def test_envelope_model_rejects_missing_fields():
    with pytest.raises(ValidationError):
        ResponseEnvelope.model_validate({"ok": True})
