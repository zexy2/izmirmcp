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
from app.core.envelope import bounded_id, bounded_text, finite_number
from app.core.geo import valid_lat_lon
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)\Z")

MARKET_RESOURCE_ID = "3e63e16e-74a9-40f6-8ad3-043ad4fa4a16"
WIFI_RESOURCE_ID = "60ca8451-d6d2-419f-b533-ab92bd5955b2"
IZMIRIM_CARD_RESOURCE_ID = "7a3efbec-fa4f-4b1e-9f9a-ac28f3608b40"
LIBRARY_RESOURCE_ID = "0c1b15b9-3f52-4437-bc16-56d366045ef5"

# Neighborhood profile layers, verified live on 2026-10-28. Both are keyed by
# district + mahalle name and join cleanly onto the muhtarlık inventory.
TAXI_STAND_RESOURCE_ID = "64a72577-5f4c-404c-8842-780d88f351df"

BUILDING_RESOURCE_ID = "54af6862-2d36-48d0-838f-a42133e8b943"
POPULATION_RESOURCE_ID = "7ef10678-8a84-4e43-9122-3ac15c818b51"


def parse_coordinate(value: Any) -> float | None:
    """Parse a decimal number that may use a Turkish decimal comma.

    This only answers "is this a finite decimal number". Range checking needs
    both axes at once (a latitude of 999 is a number but not a location), so
    layers call :func:`parse_lat_lon` instead of this helper.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not DECIMAL_RE.fullmatch(text):
            return None
        value = text
    return finite_number(value)


def parse_lat_lon(lat_value: Any, lon_value: Any) -> tuple[float, float] | None:
    """Return a valid WGS84 pair, or ``None`` when the row is not placeable."""
    lat = parse_coordinate(lat_value)
    lon = parse_coordinate(lon_value)
    if not valid_lat_lon(lat, lon):
        return None
    return lat, lon


def _lat_lon(lat_value: Any, lon_value: Any) -> dict[str, float | None]:
    """Mapper helper: spread a validated pair, or nulls when unusable."""
    pair = parse_lat_lon(lat_value, lon_value)
    if pair is None:
        return {"lat": None, "lon": None}
    return {"lat": pair[0], "lon": pair[1]}


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
                "id": bounded_id(item.get("_id")),
                "name": bounded_text(item.get("ADI")),
                "district": bounded_text(item.get("ILCE"), 128),
                "neighborhood": bounded_text(item.get("MAHALLE")),
                **_lat_lon(item.get("ENLEM"), item.get("BOYLAM")),
                "note": bounded_text(item.get("ACIKLAMA"), 512),
                "street": bounded_text(item.get("YOL")),
            }

        return await self._layer("market", MARKET_RESOURCE_ID, mapper)

    async def wifi_points(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": bounded_id(item.get("_id")),
                "name": bounded_text(item.get("ADI")),
                "district": bounded_text(item.get("ILCE"), 128),
                "neighborhood": bounded_text(item.get("MAHALLE")),
                "street": bounded_text(item.get("YOL")),
                **_lat_lon(item.get("ENLEM"), item.get("BOYLAM")),
            }

        return await self._layer("wifi", WIFI_RESOURCE_ID, mapper)

    async def izmirim_card_points(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": bounded_id(item.get("_id")),
                "address": bounded_text(item.get("ADDRESS")),
                "name": "İzmirim Kart dolum noktası",
                **_lat_lon(item.get("LATITUDE"), item.get("LONGITUDE")),
            }

        return await self._layer("izmirim_card", IZMIRIM_CARD_RESOURCE_ID, mapper)

    async def building_rows(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Per-neighborhood building counts (``YAPI`` + ``DIGER_YAPI``)."""

        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "district": bounded_text(item.get("ILCE"), 128),
                "name": bounded_text(item.get("MAHALLE")),
                "buildings": finite_number(item.get("YAPI")),
                "other_buildings": finite_number(item.get("DIGER_YAPI")),
            }

        return await self._layer("neighborhood_buildings", BUILDING_RESOURCE_ID, mapper)

    async def population_rows(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Per-neighborhood population by sex (values arrive as ``"130.0"``)."""

        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "district": bounded_text(item.get("ILCE_ADI") or "").strip() or None,
                "name": bounded_text(item.get("MAHALLE_ADI") or "").strip() or None,
                "male": finite_number(item.get("NUFUS_ERKEK_TOPLAM")),
                "female": finite_number(item.get("NUFUS_KADIN_TOPLAM")),
            }

        return await self._layer("neighborhood_population", POPULATION_RESOURCE_ID, mapper)

    async def taxi_stands(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Published taxi stand locations (district/mahalle/street labels)."""

        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": bounded_id(item.get("_id")),
                "name": bounded_text(item.get("ADI")),
                "district": bounded_text(item.get("ILCE"), 128),
                "neighborhood": bounded_text(item.get("MAHALLE")),
                "street": bounded_text(item.get("YOL")),
                "kapino": bounded_text(item.get("KAPINO"), 32),
                **_lat_lon(item.get("ENLEM"), item.get("BOYLAM")),
            }

        return await self._layer("taxi_stands", TAXI_STAND_RESOURCE_ID, mapper)

    async def libraries(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        def mapper(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": bounded_id(item.get("ID")),
                "name": bounded_text(item.get("KÜTÜPHANE_AD")),
                "district": bounded_text(item.get("ILCE"), 128),
                "address": bounded_text(item.get("ADRES")),
                "hours": bounded_text(item.get("CALISMA_SAATLERİ"), 128),
                "open_days": bounded_text(item.get("CALISMA_GUNLERI"), 128),
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


# The published notice file has ~124 rows. A 7.6 MB hostile CSV produced 1M
# rows and 214 MB of objects, so parsing stops at an advertised budget.
MAX_CSV_ROWS = 50_000


def parse_bus_notices(text: str, *, max_rows: int = MAX_CSV_ROWS) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=";")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(reader):
        if index >= max_rows:
            raise SourceError(f"CSV exceeded the {max_rows}-row budget")

        title = " ".join((item.get("BASLIK") or "").split())
        if not title:
            continue
        rows.append(
            {
                "line": bounded_text(item.get("HAT_NO"), 32),
                "title": title[:512],
                "starts_at": bounded_text(item.get("BASLAMA_TARIHI"), 40),
                "ends_at": bounded_text(item.get("BITIS_TARIHI"), 40),
            }
        )
    return rows


def parse_market_days(note: str | None) -> list[str]:
    """Extract weekday names from the free-text market note.

    The note is prose ("Cumartesi günü kurulmaktadır", sometimes misspelled), so
    only explicit Turkish weekday words are matched.

    Matching is token-based, not substring-based. A naive ``str.find`` is wrong
    here because "cumartesi" contains "cuma" and "pazartesi" contains "pazar":
    it reports Saturday as Friday+Saturday and Monday as Monday+Sunday, which
    makes a ``day=pazar`` query return Monday markets. Tokens are split on
    non-letters and the *longest* matching token wins, so an exact weekday word
    is never shadowed by a shorter word inside it.

    Absence of a match yields an empty list plus ``unknown`` confidence upstream,
    never a guessed day.
    """
    if not note:
        return []
    from app.core.geo import normalize_name

    folded = normalize_name(str(note))
    tokens = [token for token in re.split(r"[^a-z0-9]+", folded) if token]

    # Longest first so "cumartesi" is consumed before "cuma" can match inside it.
    ordered = sorted(
        ((token, day) for day, group in MARKET_DAY_TOKENS for token in group),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    found: list[tuple[int, str]] = []
    claimed: set[int] = set()
    for token, day in ordered:
        for index, word in enumerate(tokens):
            if index in claimed or word != token:
                continue
            claimed.add(index)
            found.append((index, day))
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
