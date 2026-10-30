"""Bounded SQL over a complete local CKAN DataStore snapshot.

These tests never touch the network. The fake client reproduces CKAN's
``datastore_search`` page shape, including the stable ``_id`` ordering the
snapshot loader requires.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app.core.settings import Settings
from app.services.datastore_sql import DatastoreSqlService

FIELDS = [
    {"id": "_id", "type": "int"},
    {"id": "ILCE", "type": "text"},
    {"id": "N", "type": "int"},
    {"id": "V", "type": "real"},
]
ROWS = [
    {"_id": 1, "ILCE": "Konak", "N": 10, "V": 1.5},
    {"_id": 2, "ILCE": "Konak", "N": 20, "V": 2.5},
    {"_id": 3, "ILCE": "Karşıyaka", "N": 5, "V": 3.5},
    {"_id": 4, "ILCE": "Karşıyaka", "N": 7, "V": 4.5},
]


def settings(**overrides) -> Settings:
    base = Settings(
        ckan_sql_allowed_resource_ids=("r1",),
        ckan_sql_max_rows=100,
        ckan_sql_max_bytes=1_000_000,
        ckan_sql_page_size=2,
        ckan_sql_snapshot_ttl_seconds=900,
        ckan_sql_load_timeout_seconds=10.0,
        ckan_sql_query_timeout_seconds=0.5,
        database_path=":memory:",
    )
    return dataclasses.replace(base, **overrides)


class FakeClient:
    def __init__(self, rows=None, fields=None, total=None):
        self.rows = list(ROWS if rows is None else rows)
        self.fields = list(FIELDS if fields is None else fields)
        self.total = len(self.rows) if total is None else total
        self.calls: list[tuple[int, int]] = []

    async def datastore_search_bounded(self, *, resource_id, limit, offset, max_bytes):
        assert resource_id == "r1"
        self.calls.append((limit, offset))
        if limit == 0:
            result = {"fields": self.fields, "records": [], "total": self.total}
        else:
            page = self.rows[offset:offset + limit]
            result = {"fields": self.fields, "records": page, "total": self.total}
        size = len(json.dumps(result, ensure_ascii=False).encode())
        if size > max_bytes:
            raise RuntimeError("byte budget exhausted")
        return result, size


@pytest.mark.asyncio
async def test_aggregate_runs_on_a_complete_snapshot():
    client = FakeClient()
    envelope = await DatastoreSqlService(settings=settings(), client=client).query(
        resource_id="r1",
        sql=(
            "SELECT ILCE, COUNT(*) AS n, ROUND(AVG(N), 1) AS avg_n "
            "FROM records GROUP BY ILCE ORDER BY n DESC"
        ),
    )
    assert envelope["ok"] is True
    assert envelope["data"] == [
        {"ILCE": "Konak", "n": 2, "avg_n": 15.0},
        {"ILCE": "Karşıyaka", "n": 2, "avg_n": 6.0},
    ]
    assert "2" in envelope["summary"] and "4" in envelope["summary"]
    assert any("snapshot_rows=4" in limit for limit in envelope["limits"])
    assert any("no_partial_aggregates" in limit for limit in envelope["limits"])


@pytest.mark.asyncio
async def test_result_limit_is_enforced_and_reported():
    envelope = await DatastoreSqlService(settings=settings(), client=FakeClient()).query(
        resource_id="r1",
        sql="SELECT ILCE, COUNT(*) AS n FROM records GROUP BY ILCE ORDER BY n DESC",
        limit=1,
    )
    assert envelope["ok"] is True
    assert len(envelope["data"]) == 1
    assert envelope["result_info"]["truncated"] is True
    assert any("kesildi" in warning.lower() for warning in envelope["warnings"])


@pytest.mark.asyncio
async def test_resource_must_be_allowlisted_before_any_download():
    client = FakeClient()
    envelope = await DatastoreSqlService(
        settings=settings(ckan_sql_allowed_resource_ids=()), client=client
    ).query(resource_id="r1", sql="SELECT COUNT(*) AS n FROM records")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "validation_error"
    assert envelope["error"]["field"] == "resource_id"
    assert client.calls == []


@pytest.mark.asyncio
async def test_malformed_sql_is_rejected_without_a_download():
    client = FakeClient()
    envelope = await DatastoreSqlService(settings=settings(), client=client).query(
        resource_id="r1", sql="SELECT * FROM records; DELETE FROM records"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "validation_error"
    assert envelope["error"]["field"] == "sql"
    assert client.calls == []


@pytest.mark.asyncio
async def test_snapshot_over_the_row_budget_is_never_partially_aggregated():
    client = FakeClient(total=101)
    envelope = await DatastoreSqlService(
        settings=settings(ckan_sql_max_rows=100), client=client
    ).query(resource_id="r1", sql="SELECT COUNT(*) AS n FROM records")
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert any("100" in warning or "budget" in warning.lower() for warning in envelope["warnings"])
    assert envelope["data"] == []


@pytest.mark.asyncio
async def test_duplicate_source_ids_are_rejected_as_an_unstable_snapshot():
    client = FakeClient(rows=[ROWS[0], dict(ROWS[0])])
    envelope = await DatastoreSqlService(settings=settings(), client=client).query(
        resource_id="r1", sql="SELECT COUNT(*) AS n FROM records"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["data"] == []


@pytest.mark.asyncio
async def test_changed_total_is_rejected_as_an_incomplete_snapshot():
    class Changing(FakeClient):
        async def datastore_search_bounded(self, *, resource_id, limit, offset, max_bytes):
            result, size = await super().datastore_search_bounded(
                resource_id=resource_id, limit=limit, offset=offset, max_bytes=max_bytes
            )
            if limit > 0:
                result = {**result, "total": result["total"] + 1}
            return result, size

    envelope = await DatastoreSqlService(settings=settings(), client=Changing()).query(
        resource_id="r1", sql="SELECT COUNT(*) AS n FROM records"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_snapshot_is_reused_between_queries():
    client = FakeClient()
    service = DatastoreSqlService(settings=settings(), client=client)
    first = await service.query(resource_id="r1", sql="SELECT COUNT(*) AS n FROM records")
    second = await service.query(resource_id="r1", sql="SELECT MIN(N) AS n FROM records")
    assert first["ok"] is True and second["ok"] is True
    assert len(client.calls) == 4, "metadata + two pages + final metadata, reused afterwards"


@pytest.mark.asyncio
async def test_source_failure_is_a_typed_temporary_error():
    class Broken:
        async def datastore_search_bounded(self, **_kwargs):
            raise RuntimeError("boom")

    envelope = await DatastoreSqlService(settings=settings(), client=Broken()).query(
        resource_id="r1", sql="SELECT COUNT(*) AS n FROM records"
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["error"]["temporary"] is True
    assert envelope["data"] == []
