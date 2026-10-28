from __future__ import annotations

import pytest

from app.core.settings import get_settings
from app.core.validation import InputValidationError
from app.services.neighborhood import NeighborhoodService
from tests.conftest import fresh

BUILDING_ROWS = [
    {"district": "Aliaga", "name": "Aşağışakran", "buildings": 326, "other_buildings": 24},
    {"district": "Konak", "name": "Alsancak", "buildings": 4100, "other_buildings": 180},
]
POPULATION_ROWS = [
    {"district": "Aliaga", "name": "Aşağışakran", "male": 130, "female": 126},
    {"district": "Konak", "name": "Alsancak", "male": 9000, "female": 9400},
]


class FakeApi:
    async def building_rows(self):
        return BUILDING_ROWS, fresh("2026-09-11T00:00:00")

    async def population_rows(self):
        return POPULATION_ROWS, fresh("2024-02-27T00:00:00")


@pytest.mark.asyncio
async def test_profile_joins_population_and_building_counts():
    envelope = await NeighborhoodService(settings=get_settings(), api=FakeApi()).profile(
        neighborhood="Alsancak", district="Konak"
    )
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["neighborhood"] == "Alsancak"
    assert row["district"] == "Konak"
    assert row["population_total"] == 18400
    assert row["population_male"] == 9000
    assert row["population_female"] == 9400
    assert row["buildings"] == 4100
    assert row["other_buildings"] == 180


@pytest.mark.asyncio
async def test_profile_reports_per_capita_and_source_years():
    envelope = await NeighborhoodService(settings=get_settings(), api=FakeApi()).profile(
        neighborhood="Alsancak", district="Konak"
    )
    row = envelope["data"][0]
    assert row["persons_per_building"] == round(18400 / 4100, 2)
    assert row["population_year"] is None or isinstance(row["population_year"], str)
    assert len(envelope["sources"]) == 2


@pytest.mark.asyncio
async def test_missing_layer_is_null_not_zero():
    class OnlyPopulation(FakeApi):
        async def building_rows(self):
            raise RuntimeError("boom")

    envelope = await NeighborhoodService(
        settings=get_settings(), api=OnlyPopulation()
    ).profile(neighborhood="Alsancak", district="Konak")
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["buildings"] is None
    assert row["persons_per_building"] is None
    assert row["population_total"] == 18400
    assert any("bina" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_neighborhood_absent_from_both_layers_is_a_validation_error():
    with pytest.raises(InputValidationError) as excinfo:
        await NeighborhoodService(settings=get_settings(), api=FakeApi()).profile(
            neighborhood="Olmayan", district="Konak"
        )
    assert excinfo.value.field == "neighborhood"


@pytest.mark.asyncio
async def test_district_lists_neighborhoods_with_data():
    envelope = await NeighborhoodService(settings=get_settings(), api=FakeApi()).profile(
        district="Konak"
    )
    assert envelope["ok"] is True
    assert [row["neighborhood"] for row in envelope["data"]] == ["Alsancak"]


@pytest.mark.asyncio
async def test_unknown_district_is_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        await NeighborhoodService(settings=get_settings(), api=FakeApi()).profile(
            district="Atlantis"
        )
    assert excinfo.value.field == "district"


@pytest.mark.asyncio
async def test_all_layers_failing_is_source_unavailable():
    class Broken(FakeApi):
        async def building_rows(self):
            raise RuntimeError("boom")

        async def population_rows(self):
            raise RuntimeError("boom")

    envelope = await NeighborhoodService(settings=get_settings(), api=Broken()).profile(
        district="Konak"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
