"""İZBAN fare, parking tariffs, traffic cameras and IZSU production — offline."""

from __future__ import annotations

import pytest

from app.connectors import izmir_api
from app.connectors.city_layers import (
    PARKING_FEE_RESOURCE_ID,
    TRAFFIC_CAMERA_RESOURCE_ID,
    WATER_PRODUCTION_RESOURCE_ID,
    CityLayerConnector,
)
from app.connectors.http import SourceError
from app.connectors.izmir_api import IzmirOpenApi
from app.connectors.schema import SchemaDriftError
from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.mcp import server
from app.services.city_info import CityInfoService
from tests.conftest import fresh

FARE_PAYLOAD = {
    "Iade60Yas": 5.7,
    "IadeOgretmen": 5.7,
    "SerbestUcret": 2,
    "MinBakiye60Yas": 9.7,
    "IadeTam": 9.5,
    "MinBakiyeSerbest": 4,
    "TamUcret": 5.12,
    "OgrenciUcret": 2.47,
    "Yas60Ucret": 4,
    "MinBakiyeOgretmen": 9.7,
    "BinisIstasyonu": "Aliağa",
    "ToplamKm": 41.503,
    "IadeOgrenci": 4.75,
    "MinBakiyeTam": 14.62,
    "IadeSerbest": 2,
    "OgretmenUcret": 4,
    "MinBakiyeOgrenci": 7.22,
    "InisIstasyonu": "Mavişehir",
}

STATIONS = [
    {"id": 1, "name": "Aliağa", "lat": 38.79, "lon": 26.97},
    {"id": 10, "name": "Mavişehir", "lat": 38.47, "lon": 27.08},
    {"id": 20, "name": "İnciraltı Hilal", "lat": 38.42, "lon": 27.14},
    {"id": 21, "name": "Hilal", "lat": 38.43, "lon": 27.15},
    {"id": 30, "name": "Şirinyer", "lat": 38.39, "lon": 27.15},
    {"id": 31, "name": "Şirinyer Köprü", "lat": 38.39, "lon": 27.15},
]


class FakeApi:
    def __init__(self, *, fare_error: Exception | None = None):
        self.fare_calls: list[tuple] = []
        self.fare_error = fare_error

    async def izban_stations(self):
        return STATIONS, fresh()

    async def izban_fare(self, from_id, to_id, *, transfer, htt):
        self.fare_calls.append((from_id, to_id, transfer, htt))
        if self.fare_error:
            raise self.fare_error
        return {
            "from_station": "Aliağa",
            "to_station": "Mavişehir",
            "distance_km": 41.5,
            "fares": {"full": 5.12},
        }, fresh()


class FakeLayers:
    def __init__(self, *, error: Exception | None = None):
        self.error = error

    async def parking_fee_rows(self):
        if self.error:
            raise self.error
        return [
            {"id": 1, "name": "Alsancak Tam Otomatik Otoparkı", "fees_try": {"h0_2": 60.0}},
            {"id": 12, "name": "Konak Katlı Otoparkı", "fees_try": {"h0_2": 40.0}},
            {"id": 13, "name": "İnciraltı Çınar Otoparkı", "fees_try": {"h0_2": None}},
        ], fresh()

    async def traffic_camera_rows(self):
        if self.error:
            raise self.error
        return [
            {"id": 1, "name": "TEPECIK KAVSAGI", "lat": 38.42222492, "lon": 27.15298285},
            {"id": 3, "name": "OTOGAR KAVSAGI", "lat": 38.42774045, "lon": 27.21271588},
            {"id": 9, "name": "KOORDINATSIZ", "lat": None, "lon": None},
        ], fresh()

    async def water_production_rows(self):
        if self.error:
            raise self.error
        return [
            {"id": 225, "name": "Tahtalı Barajı", "kind": "Baraj", "production": 95000.0},
            {"id": 229, "name": "Sarıkız Kuyuları", "kind": "Kuyu", "production": 58100.0},
        ], fresh()


def service(**kwargs) -> CityInfoService:
    return CityInfoService(
        settings=get_settings(),
        api=kwargs.get("api", FakeApi()),
        layers=kwargs.get("layers", FakeLayers()),
    )


# --- İZBAN fare -----------------------------------------------------------


@pytest.mark.asyncio
async def test_fare_by_ids_builds_the_validated_call():
    api = FakeApi()
    envelope = await service(api=api).izban_fare(from_station=1, to_station=10, transfer=True, htt=False)
    assert envelope["ok"] is True
    assert api.fare_calls == [(1, 10, True, False)]
    assert envelope["data"][0]["from_id"] == 1 and envelope["data"][0]["to_id"] == 10
    assert "transfer=true" in envelope["limits"] and "htt=false" in envelope["limits"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "expected"), [("aliaga", 1), ("ALİAĞA", 1), ("mavisehir", 10), ("MAVİŞEHİR", 10)])
async def test_fare_station_names_are_turkish_case_insensitive(name, expected):
    api = FakeApi()
    other = 10 if expected == 1 else 1
    await service(api=api).izban_fare(from_station=name, to_station=other)
    assert api.fare_calls[0][0] == expected


@pytest.mark.asyncio
async def test_exact_name_wins_over_substring_candidates():
    api = FakeApi()
    await service(api=api).izban_fare(from_station="hilal", to_station=1)
    assert api.fare_calls[0][0] == 21


@pytest.mark.asyncio
async def test_ambiguous_name_lists_candidates_and_skips_the_fare_call():
    api = FakeApi()
    with pytest.raises(InputValidationError) as info:
        await service(api=api).izban_fare(from_station="şirin", to_station=1)
    assert info.value.field == "from_station"
    assert "Şirinyer (30)" in str(info.value) and "Şirinyer Köprü (31)" in str(info.value)
    assert api.fare_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"from_station": "yokboyle", "to_station": 1}, "from_station"),
        ({"from_station": 1, "to_station": 999}, "to_station"),
        ({"from_station": 0, "to_station": 1}, "from_station"),
        ({"from_station": -3, "to_station": 1}, "from_station"),
        ({"from_station": True, "to_station": 1}, "from_station"),
        ({"from_station": 1.5, "to_station": 1}, "from_station"),
        ({"from_station": "   ", "to_station": 1}, "from_station"),
        ({"from_station": 1, "to_station": "1"}, "to_station"),
        ({"from_station": 1, "to_station": 10, "transfer": 1}, "transfer"),
        ({"from_station": 1, "to_station": 10, "htt": "true"}, "htt"),
    ],
)
async def test_fare_rejects_bad_input_before_the_fare_call(kwargs, field):
    api = FakeApi()
    with pytest.raises(InputValidationError) as info:
        await service(api=api).izban_fare(**kwargs)
    assert info.value.field == field
    assert api.fare_calls == []


@pytest.mark.asyncio
async def test_fare_source_failure_is_a_typed_envelope():
    envelope = await service(api=FakeApi(fare_error=SourceError("HTTP 500"))).izban_fare(from_station=1, to_station=10)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] in {"source_unavailable", "schema_drift"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("transfer", "htt", "path"), [(False, False, "/0/false"), (True, True, "/1/true")])
async def test_fare_connector_encodes_flags_and_maps_fields(monkeypatch, transfer, htt, path):
    urls: list[str] = []

    async def fake_get_json(url, **_kwargs):
        urls.append(url)
        return FARE_PAYLOAD

    monkeypatch.setattr(izmir_api, "get_json", fake_get_json)
    fare, _info = await IzmirOpenApi(get_settings()).izban_fare(1, 10, transfer=transfer, htt=htt)
    assert urls[0].endswith(f"/izban/tutarhesaplama/1/10{path}")
    assert fare["fares"]["full"] == 5.12
    assert fare["fares"]["student"] == 2.47
    assert fare["refunds"]["full"] == 9.5
    assert fare["min_balance"]["age_60"] == 9.7
    assert fare["from_station"] == "Aliağa" and fare["distance_km"] == 41.503


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"Message": "Lutfen gecerli parametre giriniz."}, {"TamUcret": "abc"}])
async def test_fare_connector_rejects_drifted_payloads(monkeypatch, payload):
    async def fake_get_json(url, **_kwargs):
        return payload

    monkeypatch.setattr(izmir_api, "get_json", fake_get_json)
    with pytest.raises(SchemaDriftError):
        await IzmirOpenApi(get_settings()).izban_fare(2, 11, transfer=False, htt=False)


@pytest.mark.asyncio
async def test_fare_tool_reports_validation_envelope():
    envelope = await server.izmir_fare(from_station=1, to_station=1)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "validation_error"


# --- Parking fees -----------------------------------------------------------


@pytest.mark.asyncio
async def test_parking_fee_name_filter_is_a_plain_substring():
    envelope = await service().parking_fees(query="konak")
    assert [row["id"] for row in envelope["data"]] == [12]
    envelope = await service().parking_fees(query="İNCİRALTI")
    assert [row["id"] for row in envelope["data"]] == [13]
    envelope = await service().parking_fees(query=".*")
    assert envelope["ok"] is True and envelope["data"] == []


@pytest.mark.asyncio
async def test_parking_fees_point_to_live_occupancy_and_cap_the_limit():
    envelope = await service().parking_fees(limit=1)
    assert len(envelope["data"]) == 1 and envelope["result_info"]["matched"] == 3
    assert any("izmir_nearby" in warning for warning in envelope["warnings"])
    with pytest.raises(InputValidationError):
        await service().parking_fees(limit=10_000)


@pytest.mark.asyncio
async def test_parking_fee_mapper_normalizes_blank_cells():
    class Ckan:
        async def datastore_search(self, **kwargs):
            assert kwargs["resource_id"] == PARKING_FEE_RESOURCE_ID
            return {
                "total": 1,
                "records": [
                    {
                        "_id": 3,
                        "Otopark / Fiyat": "Hatay Pazaryeri Yeraltı Katlı\r\nOtoparkı",
                        "0-2 saat": 40,
                        "0-3 saat": "",
                        "0-1 Saat": None,
                        "Aylık Abone Ücreti": 1400,
                    }
                ],
            }

    rows, _ = await CityLayerConnector(settings=get_settings(), ckan=Ckan()).parking_fee_rows()
    assert rows[0]["name"] == "Hatay Pazaryeri Yeraltı Katlı Otoparkı"
    fees = rows[0]["fees_try"]
    assert fees["h0_2"] == 40.0 and fees["monthly_subscription"] == 1400.0
    assert fees["h0_3"] is None and fees["h0_1"] is None and fees["lost_ticket"] is None


# --- Traffic cameras --------------------------------------------------------


@pytest.mark.asyncio
async def test_cameras_near_a_point_are_ranked_and_skip_unplaced_rows():
    envelope = await service().traffic_cameras(lat=38.4222, lon=27.1530, radius_m=10_000)
    assert [row["id"] for row in envelope["data"]] == [1, 3]
    assert envelope["data"][0]["distance_m"] < envelope["data"][1]["distance_m"]
    assert any("yayın" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_cameras_without_point_list_everything_and_filter_by_name():
    envelope = await service().traffic_cameras()
    assert envelope["result_info"]["matched"] == 3
    envelope = await service().traffic_cameras(query="otogar")
    assert [row["id"] for row in envelope["data"]] == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"lat": 38.4}, "lat"),
        ({"radius_m": 500}, "radius_m"),
        ({"lat": 91.0, "lon": 27.1}, "lat"),
        ({"lat": 38.4, "lon": 181.0}, "lon"),
        ({"lat": 38.4, "lon": 27.1, "radius_m": 50_001}, "radius_m"),
        ({"lat": 38.4, "lon": 27.1, "radius_m": 0}, "radius_m"),
    ],
)
async def test_camera_inputs_are_range_checked(kwargs, field):
    with pytest.raises(InputValidationError) as info:
        await service().traffic_cameras(**kwargs)
    assert info.value.field == field


@pytest.mark.asyncio
async def test_camera_radius_allows_fifty_km():
    envelope = await service().traffic_cameras(lat=38.4, lon=27.1, radius_m=50_000)
    assert envelope["ok"] is True


@pytest.mark.asyncio
async def test_camera_tool_rejects_boolean_coordinates():
    envelope = await server.izmir_traffic_cameras(lat=True, lon=27.1)
    assert envelope["ok"] is False and envelope["error"]["field"] == "lat"


@pytest.mark.asyncio
async def test_camera_mapper_reads_resource_and_coordinates():
    class Ckan:
        async def datastore_search(self, **kwargs):
            assert kwargs["resource_id"] == TRAFFIC_CAMERA_RESOURCE_ID
            return {
                "total": 2,
                "records": [
                    {"_id": 1, "ADI": "TEPECIK KAVSAGI", "ENLEM": 38.42222492, "BOYLAM": 27.15298285},
                    {"_id": 2, "ADI": "BOZUK", "ENLEM": 999, "BOYLAM": 27.1},
                ],
            }

    rows, _ = await CityLayerConnector(settings=get_settings(), ckan=Ckan()).traffic_camera_rows()
    assert rows[0] == {"id": 1, "name": "TEPECIK KAVSAGI", "lat": 38.42222492, "lon": 27.15298285}
    assert rows[1]["lat"] is None and rows[1]["lon"] is None


# --- IZSU water production --------------------------------------------------


@pytest.mark.asyncio
async def test_water_production_is_labelled_an_undated_snapshot():
    envelope = await service().water_production()
    assert envelope["ok"] is True
    assert "anlık görüntü" in envelope["summary"]
    assert any("bugünkü" in warning for warning in envelope["warnings"])
    assert any("Birim" in warning for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_water_production_name_filter():
    envelope = await service().water_production(name="tahtali")
    assert [row["id"] for row in envelope["data"]] == [225]


@pytest.mark.asyncio
async def test_water_production_mapper():
    class Ckan:
        async def datastore_search(self, **kwargs):
            assert kwargs["resource_id"] == WATER_PRODUCTION_RESOURCE_ID
            return {
                "total": 1,
                "records": [
                    {
                        "_id": 1,
                        "TUR_ADI": "Kuyu",
                        "BARAJ_KUYU_ADI": "Sarıkız Kuyuları",
                        "BARAJ_KUYU_ID": 229,
                        "URETIM_MIKTARI": 58100,
                    }
                ],
            }

    rows, _ = await CityLayerConnector(settings=get_settings(), ckan=Ckan()).water_production_rows()
    assert rows == [{"id": 229, "name": "Sarıkız Kuyuları", "kind": "Kuyu", "production": 58100.0}]


# --- Shared failure handling ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["parking_fees", "traffic_cameras", "water_production"])
async def test_layer_failures_are_typed_envelopes(method):
    envelope = await getattr(service(layers=FakeLayers(error=SourceError("HTTP 502"))), method)()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_empty_or_html_layer_is_a_source_error():
    class EmptyCkan:
        async def datastore_search(self, **_kwargs):
            return {"total": 0, "records": []}

    with pytest.raises(SourceError):
        await CityLayerConnector(settings=get_settings(), ckan=EmptyCkan()).water_production_rows()

    class HtmlCkan:
        async def datastore_search(self, **_kwargs):
            return {"total": 1, "records": "<html>bakım</html>"}

    with pytest.raises(SourceError):
        await CityLayerConnector(settings=get_settings(), ckan=HtmlCkan()).traffic_camera_rows()
