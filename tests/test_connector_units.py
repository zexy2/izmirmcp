"""Offline unit tests for thinly covered connectors and the stdio entrypoint."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import app.connectors.ckan as ckan_mod
import app.connectors.operators as ops
from app.connectors.ckan import CkanClient, CkanError, CkanNotFoundError, CkanSchemaDriftError
from app.connectors.http import SourceError
from app.core.settings import Settings


@pytest.mark.parametrize(
    "payload",
    [[], {"isSuccessful": False}, {"data": {"x": 1}}],
)
def test_metro_parser_rejects_bad_shapes(payload: Any) -> None:
    with pytest.raises(SourceError):
        ops.parse_metro_announcements(payload)


def test_metro_parser_flattens_rows() -> None:
    assert ops.parse_metro_announcements({"data": None}) == []
    rows = ops.parse_metro_announcements(
        {"data": ["junk", {"title": "  "}, {"id": 7, "name": "Sefer  değişikliği", "content": "x", "date": "d"}]}
    )
    assert rows == [{"id": "7", "title": "Sefer değişikliği", "summary": "x", "published_at": "d", "url": None}]


@pytest.mark.parametrize("payload", [[], {"data": {"data": "nope"}}])
def test_ferry_parser_rejects_bad_shapes(payload: Any) -> None:
    with pytest.raises(SourceError):
        ops.parse_ferry_announcements(payload)


def test_ferry_parser_nested_and_flat() -> None:
    assert ops.parse_ferry_announcements({}) == []
    assert ops.parse_ferry_announcements({"data": {}}) == []
    rows = ops.parse_ferry_announcements(
        {"data": {"data": [1, {"title": ""}, {"id": 1, "title": "Hat", "slug": "hat-1", "createdAt": "t"}]}}
    )
    assert rows[0]["url"] == "https://www.izdeniz.com.tr/duyurular/hat-1"
    assert rows[0]["published_at"] == "t"
    flat = ops.parse_ferry_announcements({"data": [{"title": "Düz"}]})
    assert flat[0]["url"] is None


async def test_operator_connector_fetches_through_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_get_json(url: str, **_: Any) -> Any:
        seen.append(url)
        return {"data": [{"title": "Duyuru"}]}

    async def fake_cache(key: str, *, ttl_seconds: int, loader: Any) -> Any:
        return await loader(), key

    monkeypatch.setattr(ops, "get_json", fake_get_json)
    monkeypatch.setattr(ops, "cached_source_data", fake_cache)
    connector = ops.OperatorAnnouncementConnector(Settings())
    metro, key = await connector.metro_announcements()
    ferry, _ = await connector.ferry_announcements()
    assert metro[0]["title"] == "Duyuru" and key == "operator.metro.announcements"
    assert ferry[0]["title"] == "Duyuru"
    assert seen[0].startswith(ops.METRO_BASE_URL) and seen[1].startswith(ops.FERRY_BASE_URL)


def test_ckan_result_error_taxonomy() -> None:
    client = CkanClient(Settings())
    with pytest.raises(CkanSchemaDriftError):
        client._result("a", [])
    with pytest.raises(CkanNotFoundError):
        client._result("a", {"success": False, "error": {"message": "Not found: x"}})
    with pytest.raises(CkanError) as exc:
        client._result("a", {"success": False, "error": "boom"})
    assert not isinstance(exc.value, CkanNotFoundError)
    assert client._result("a", {"success": True, "result": 3}) == 3


async def test_ckan_datastore_search_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_get_json(url: str, **_: Any) -> Any:
        captured["q"] = parse_qs(urlsplit(url).query)
        return {"success": True, "result": {"records": []}}

    monkeypatch.setattr(ckan_mod, "get_json", fake_get_json)
    client = CkanClient(Settings())
    result = await client.datastore_search(
        resource_id="r", limit=5, filters={"ilce": "Konak"}, query="q", sort="x", include_total=True
    )
    assert result == {"records": []}
    q = captured["q"]
    assert q["filters"] == ['{"ilce": "Konak"}'] and q["q"] == ["q"]
    assert q["sort"] == ["x"] and q["include_total"] == ["true"]


async def test_ckan_bounded_page(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(url: str, **_: Any) -> Any:
        assert "sort=_id+asc" in url
        return {"success": True, "result": {"total": 1}}, 42

    async def bad(url: str, **_: Any) -> Any:
        return {"success": True, "result": []}, 1

    client = CkanClient(Settings())
    monkeypatch.setattr(ckan_mod, "get_json_with_size", ok)
    assert await client.datastore_search_bounded(resource_id="r", limit=1, offset=0, max_bytes=10) == (
        {"total": 1},
        42,
    )
    monkeypatch.setattr(ckan_mod, "get_json_with_size", bad)
    with pytest.raises(CkanSchemaDriftError):
        await client.datastore_search_bounded(resource_id="r", limit=1, offset=0, max_bytes=10)


def test_stdio_main_runs_stdio_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.stdio as stdio

    calls: list[str] = []

    class FakeServer:
        def run(self, *, transport: str) -> None:
            calls.append(transport)

    monkeypatch.setattr(stdio, "create_mcp_server", lambda settings: FakeServer())
    stdio.main()
    assert calls == ["stdio"]
