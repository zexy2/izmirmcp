"""P4: services must turn connector failures into typed envelopes.

Several services used to call their connector without a guard, so an upstream
HTTP failure escaped as ``UnexpectedToolError`` instead of the documented
``source_unavailable`` / ``source_rate_limited`` / ``source_timeout`` taxonomy.
These tests pin the corrected behaviour without any network access.
"""

from __future__ import annotations

import httpx
import pytest

from app.connectors.http import SourceError, SourceRateLimitedError, SourceTimeoutError
from app.core.settings import get_settings
from app.mcp.registry import create_mcp_server
from app.services.air import AirQualityService
from app.services.transit import TransitService
from app.services.water import WaterService

CSV = "BARAJ_KUYU_ID;BARAJ_KUYU_ADI;DURUM_TARIHI;DOLULUK_ORANI\n1;Tahtalı;2026-10-27;42,5\n"


class _FailingClient:
    def __init__(self, exc: Exception):
        self.exc = exc

    async def air_quality(self, *args, **kwargs):
        raise self.exc

    async def metro_stations(self, *args, **kwargs):
        raise self.exc

    async def metro_schedule(self, *args, **kwargs):
        raise self.exc

    async def dams(self, *args, **kwargs):
        raise self.exc


@pytest.mark.parametrize(
    "exc,code,temporary",
    [
        (SourceError("boom"), "source_unavailable", True),
        (SourceRateLimitedError("429"), "source_rate_limited", True),
        (SourceTimeoutError("timeout"), "source_timeout", True),
    ],
)
@pytest.mark.asyncio
async def test_air_quality_maps_connector_failures(exc, code, temporary):
    service = AirQualityService(settings=get_settings(), api=_FailingClient(exc))
    envelope = await service.readings(day="2026-10-01")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == code
    assert envelope["error"]["temporary"] is temporary
    assert envelope["freshness"]["status"] in {"broken", "stale"}
    assert envelope["warnings"]


@pytest.mark.asyncio
async def test_air_quality_does_not_swallow_non_source_bugs():
    """A programming bug must not be relabelled as a source outage."""
    service = AirQualityService(settings=get_settings(), api=_FailingClient(RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        await service.readings(day="2026-10-01")


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [SourceError("boom"), httpx.ConnectError("no route")])
async def test_transit_stations_and_schedule_map_connector_failures(exc):
    service = TransitService(settings=get_settings(), api=_FailingClient(exc))
    stations = await service.stations(mode="metro")
    schedule = await service.schedule(mode="metro")
    for envelope in (stations, schedule):
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "source_unavailable"
        assert envelope["error"]["temporary"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc,code",
    [
        (SourceError("boom"), "source_unavailable"),
        (SourceRateLimitedError("429"), "source_rate_limited"),
        (SourceTimeoutError("timeout"), "source_timeout"),
    ],
)
async def test_water_dams_map_connector_failures(exc, code):
    service = WaterService(settings=get_settings(), client=_FailingClient(exc))
    envelope = await service.status(kind="dams")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == code
    assert envelope["warnings"]


@pytest.mark.asyncio
async def test_water_faults_stays_typed_owner_of_the_gap():
    service = WaterService(settings=get_settings(), client=_FailingClient(SourceError("x")))
    envelope = await service.status(kind="faults")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert "kind=faults" in envelope["limits"]


@pytest.mark.asyncio
async def test_water_unusable_csv_is_a_source_error_not_a_crash():
    class _Empty:
        async def dams(self):
            raise ValueError("İZSU dam CSV contained no usable rows")

    service = WaterService(settings=get_settings(), client=_Empty())
    envelope = await service.status(kind="dams")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


def _settings_with(url: str):
    from app.core.settings import Settings

    return Settings(**{**get_settings().__dict__, "izsu_dams_csv_url": url})


@pytest.mark.asyncio
async def test_water_service_end_to_end_500_is_typed(monkeypatch):
    from app.core.source_cache import clear_cache

    clear_cache()

    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(500, text="no"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.connectors.http.httpx.AsyncClient", _client)
    service = WaterService(settings=_settings_with("https://example.invalid/dams.csv"))
    envelope = await service.status(kind="dams")
    clear_cache()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_air_tool_call_returns_envelope_instead_of_raising(monkeypatch):
    """The registry surface must never leak UnexpectedToolError for a source 503."""
    from app.core.source_cache import clear_cache

    clear_cache()

    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(503, text="down"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.connectors.http.httpx.AsyncClient", _client)
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_air_quality", {"date": "2026-10-01"})
    import json

    payload = json.loads(result.content[0].text)
    clear_cache()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_transit_tool_call_returns_envelope_instead_of_raising(monkeypatch):
    from app.core.source_cache import clear_cache

    clear_cache()

    real_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(502, text="bad"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.connectors.http.httpx.AsyncClient", _client)
    server = create_mcp_server(get_settings())
    result = await server.call_tool("izmir_transit_stations", {"mode": "metro"})
    import json

    payload = json.loads(result.content[0].text)
    clear_cache()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "source_unavailable"
