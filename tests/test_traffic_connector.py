"""The recent-traffic page must ask CKAN for newest-first rows, once.

Filtered queries keep the full scan (a match can sit anywhere in the dataset),
but an unfiltered small limit must not page 18,731 rows.
"""

from __future__ import annotations

import pytest

from app.connectors.city_layers import TRAFFIC_RESOURCE_ID, CityLayerConnector
from app.connectors.http import SourceError
from app.core.settings import get_settings


def record(minute: str, segment: str = "Marina Kavşağı") -> dict:
    return {
        "TARIH": "2026-10-22T00:00:00",
        "SAAT": minute,
        "BASLAMA": segment,
        "BITIS": "Konak Pier",
        "HIZ": 26.0,
        "SURE": 15.0,
    }


class FakeCkan:
    def __init__(self, records: list[dict], *, total: int):
        self.records = records
        self.total = total
        self.calls: list[dict] = []

    async def datastore_search(self, **kwargs):
        self.calls.append(kwargs)
        return {"records": self.records, "total": self.total}


@pytest.mark.asyncio
async def test_recent_page_asks_for_one_sorted_server_page():
    ckan = FakeCkan([record("19:05:00"), record("18:05:00")], total=18_731)
    connector = CityLayerConnector(settings=get_settings(), ckan=ckan)

    rows, info, total = await connector.traffic_recent(2)

    assert len(ckan.calls) == 1
    call = ckan.calls[0]
    assert call["resource_id"] == TRAFFIC_RESOURCE_ID
    assert call["limit"] == 2
    assert call["offset"] == 0
    assert call["sort"] == "TARIH desc,SAAT desc"
    assert call["include_total"] is True
    assert total == 18_731
    assert [row["observed_at"] for row in rows] == [
        "2026-10-22T19:05:00",
        "2026-10-22T18:05:00",
    ]
    assert info.source_updated_at == "2026-10-22T19:05:00"


@pytest.mark.asyncio
async def test_recent_page_without_usable_rows_is_a_source_error():
    ckan = FakeCkan([{**record("19:05:00"), "BASLAMA": None}], total=1)
    connector = CityLayerConnector(settings=get_settings(), ckan=ckan)

    with pytest.raises(SourceError):
        await connector.traffic_recent(1)
