"""Static İzmir city layers published as CKAN DataStore resources.

Every layer here was verified live on 2026-10-28 with the exact column names
below (see ``reports/eshot-ulasim-kaynak-arastirmasi.md`` and
``reports/izmir-sehir-katmanlari.md``). Coordinate parsing tolerates the
source's Turkish decimal comma without rescaling arbitrary values.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from app.connectors.ckan import CkanClient
from app.connectors.http import SourceError, get_text
from app.core.envelope import finite_number
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)\Z")

MARKET_RESOURCE_ID = "3e63e16e-74a9-40f6-8ad3-043ad4fa4a16"
WIFI_RESOURCE_ID = "60ca8451-d6d2-419f-b533-ab92bd5955b2"
IZMIRIM_CARD_RESOURCE_ID = "7a3efbec-fa4f-4b1e-9f9a-ac28f3608b40"
LIBRARY_RESOURCE_ID = "0c1b15b9-3f52-4437-bc16-56d366045ef5"


def parse_coordinate(value: Any) -> float | None:
    """Parse a decimal WGS84 coordinate that may use a Turkish decimal comma."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not DECIMAL_RE.fullmatch(text):
            return None
        value = text
    return finite_number(value)


def parse_gtfs_style_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


class CityLayerConnector:
    def __init__(self, *, settings: Settings, ckan: CkanClient | None = None):
        self.settings = settings
        self.ckan = ckan or CkanClient(settings)

    async def _datastore_rows(self, resource_id: str) -> list[dict[str, Any]]:
        page_size = self.settings.eshot_datastore_page_size
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.ckan.datastore_search(
                resource_id=resource_id, limit=page_size, offset=offset
            )
            records = page.get("records") or []
            if not isinstance(records, list):
                raise SourceError("datastore records were not a list")
            rows.extend(record for record in records if isinstance(record, dict))
            total = page.get("total")
            offset += len(records)
            if not records or not isinstance(total, int) or offset >= total:
                break
        if not rows:
            raise SourceError("city layer returned no rows")
        return rows

    async def _layer(
        self, key: str, resource_id: str, mapper
    ) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            rows = [mapper(item) for item in await self._datastore_rows(resource_id)]
            usable = [row for row in rows if row.get("name") or row.get("address")]
            if not usable:
                raise SourceError(f"city layer {key} contained no usable rows")
            return usable

        return await cached_source_data(
            f"city_layer.{key}",
            ttl_seconds=self.settings.city_layer_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.city_layer_stale_if_error_seconds,
            loader=loader,
        )

    async def market_rows(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": str(item.get("_id")) if item.get("_id") is not None else None,
                "name": (item.get("ADI") or "").strip() or None,
                "district": (item.get("ILCE") or "").strip() or None,
                "neighborhood": (item.get("MAHALLE") or "").strip() or None,
                "lat": parse_coordinate(item.get("ENLEM")),
                "lon": parse_coordinate(item.get("BOYLAM")),
                "note": " ".join((item.get("ACIKLAMA") or "").split()) or None,
                "street": (item.get("YOL") or "").strip() or None,
            }

        return await self._layer("market", MARKET_RESOURCE_ID, mapper)

    async def wifi_points(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": str(item.get("_id")) if item.get("_id") is not None else None,
                "name": (item.get("ADI") or "").strip() or None,
                "district": (item.get("ILCE") or "").strip() or None,
                "neighborhood": (item.get("MAHALLE") or "").strip() or None,
                "street": (item.get("YOL") or "").strip() or None,
                "lat": parse_coordinate(item.get("ENLEM")),
                "lon": parse_coordinate(item.get("BOYLAM")),
            }

        return await self._layer("wifi", WIFI_RESOURCE_ID, mapper)

    async def izmirim_card_points(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": str(item.get("_id")) if item.get("_id") is not None else None,
                "address": " ".join((item.get("ADDRESS") or "").split()) or None,
                "name": "İzmirim Kart dolum noktası",
                "lat": parse_coordinate(item.get("LATITUDE")),
                "lon": parse_coordinate(item.get("LONGITUDE")),
            }

        return await self._layer("izmirim_card", IZMIRIM_CARD_RESOURCE_ID, mapper)

    async def libraries(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": str(item.get("ID")) if item.get("ID") is not None else None,
                "name": " ".join((item.get("KÜTÜPHANE_AD") or "").split()) or None,
                "district": (item.get("ILCE") or "").strip() or None,
                "address": " ".join((item.get("ADRES") or "").split()) or None,
                "hours": " ".join((item.get("CALISMA_SAATLERİ") or "").split()) or None,
                "open_days": " ".join((item.get("CALISMA_GUNLERI") or "").split()) or None,
                "opened_year": item.get("ACILIS_YILI"),
                # The published layer has no coordinates; never fabricate them.
                "lat": None,
                "lon": None,
            }

        return await self._layer("library", LIBRARY_RESOURCE_ID, mapper)


class BusNoticeConnector:
    """EShot line notices from the published semicolon-delimited CSV."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def bus_notices(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            text = await get_text(
                self.settings.eshot_notices_csv_url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
            )
            rows = parse_bus_notices(text)
            if not rows:
                raise SourceError("EShot notices CSV contained no usable rows")
            return rows

        return await cached_source_data(
            "eshot.notices",
            ttl_seconds=self.settings.eshot_notices_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.eshot_stale_if_error_seconds,
            loader=loader,
        )


def parse_bus_notices(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=";")
    rows: list[dict[str, Any]] = []
    for item in reader:
        title = " ".join((item.get("BASLIK") or "").split())
        if not title:
            continue
        rows.append(
            {
                "line": (item.get("HAT_NO") or "").strip() or None,
                "title": title,
                "starts_at": (item.get("BASLAMA_TARIHI") or "").strip() or None,
                "ends_at": (item.get("BITIS_TARIHI") or "").strip() or None,
            }
        )
    return rows


def parse_market_days(note: str | None) -> list[str]:
    """Extract weekday names from the free-text market note.

    The note is prose ("Cumartesi günü kurulmaktadır", sometimes misspelled), so
    only explicit Turkish weekday words are matched. Absence of a match yields an
    empty list plus an ``unknown`` confidence upstream, never a guessed day.
    """
    if not note:
        return []
    folded = note.casefold()
    from app.core.geo import normalize_name

    folded = normalize_name(folded)
    found: list[tuple[int, str]] = []
    for day, tokens in MARKET_DAY_TOKENS:
        for token in tokens:
            index = folded.find(token)
            if index >= 0:
                found.append((index, day))
                break
    return [day for _index, day in sorted(found)]


MARKET_DAY_TOKENS = (
    ("monday", ("pazartesi",)),
    ("tuesday", ("sali",)),
    ("wednesday", ("carsamba",)),
    ("thursday", ("persembe",)),
    ("friday", ("cuma",)),
    ("saturday", ("cumartesi",)),
    ("sunday", ("pazar",)),
)
