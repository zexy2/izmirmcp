from __future__ import annotations

import pytest

from app.connectors.ckan import CkanNotFoundError
from app.core.settings import get_settings
from app.services.catalog import CatalogService

DATASET = {
    "id": "abc-123",
    "name": "otopark-doluluk",
    "title": "Otopark Doluluk",
    "notes": "İZELMAN otoparkları",
    "license_title": "Izmir Metropolitan Municipality Open Data License",
    "metadata_modified": "2026-10-20T00:00:00",
    "tags": [{"name": "otopark"}],
    "resources": [
        {"id": "res-1", "name": "Doluluk", "format": "CSV", "datastore_active": True},
        {"id": "res-2", "name": "Ham", "format": "XLSX", "datastore_active": False},
    ],
}


class FakeClient:
    async def package_search(self, *, query, rows, formats=None):
        return {"count": 1, "results": [DATASET]}

    async def package_show(self, dataset_id):
        if dataset_id == "missing":
            raise CkanNotFoundError("not found")
        return DATASET

    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        if resource_id == "missing":
            raise CkanNotFoundError("not found")
        return {
            "fields": [{"id": "ILCE"}, {"id": "KAPASITE"}],
            "records": [{"ILCE": "Konak", "KAPASITE": 43}],
            "total": 1,
        }


@pytest.mark.asyncio
async def test_search_maps_dataset_summary():
    envelope = await CatalogService(settings=get_settings(), client=FakeClient()).search_datasets(
        query="otopark", limit=5
    )
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["id"] == "abc-123"
    assert row["formats"] == ["CSV", "XLSX"]
    assert row["datastore_active_count"] == 1
    assert row["relevance"]["score"] >= 3
    assert envelope["result_info"]["matched"] == 1


@pytest.mark.asyncio
async def test_get_dataset_not_found_is_structured():
    envelope = await CatalogService(settings=get_settings(), client=FakeClient()).get_dataset("missing")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_query_rejects_unknown_filter_field():
    envelope = await CatalogService(settings=get_settings(), client=FakeClient()).query_resource(
        resource_id="res-1", filters={"MAHALLE": "Alsancak"}, limit=5
    )
    assert envelope["ok"] is False
    assert envelope["error"]["field"] == "filters"
    assert "ILCE" in envelope["warnings"][0]


@pytest.mark.asyncio
async def test_query_returns_records_with_total():
    envelope = await CatalogService(settings=get_settings(), client=FakeClient()).query_resource(
        resource_id="res-1", filters={"ILCE": "Konak"}, limit=5
    )
    assert envelope["ok"] is True
    assert envelope["data"] == [{"ILCE": "Konak", "KAPASITE": 43}]
    assert envelope["result_info"]["matched"] == 1
