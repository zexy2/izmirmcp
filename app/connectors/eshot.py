"""EShot bus sources: documented stops, live arrivals and the published GTFS feed.

Every endpoint here was verified live on 2026-10-28 (see
``reports/eshot-ulasim-kaynak-arastirmasi.md``). Undocumented guesses such as
``/api/eshot/...`` returned 404 and are deliberately absent.
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import date
from typing import Any

from app.connectors.ckan import CkanClient
from app.connectors.http import SourceError, get_json, get_zip, get_zip_members
from app.connectors.schema import decode_member, expect_type
from app.core.envelope import bounded_id, bounded_text, finite_number
from app.core.geo import valid_lat_lon
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

WEEKDAY_COLUMNS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
GTFS_MEMBERS = {
    "stops.txt": 8 * 1024 * 1024,
    "routes.txt": 2 * 1024 * 1024,
    "trips.txt": 8 * 1024 * 1024,
    "calendar.txt": 64 * 1024,
}


async def _throttle() -> None:
    """Acquire an İZTEK token from the shared per-source budget.

    The endpoint answered HTTP 429 under a burst, so every caller of this
    connector shares one bucket. A too-long wait surfaces as
    ``SourceRateLimitExceeded`` and the service maps it to
    ``source_rate_limited``.
    """
    from app.core.source_limits import source_limiters

    await source_limiters().acquire("iztek")


def parse_gtfs_date(value: str | None) -> str | None:
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    except ValueError:
        return None


def _gtfs_bool(value: str | None) -> bool | None:
    text = (value or "").strip()
    if text == "1":
        return True
    if text == "0":
        return False
    return None


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def parse_comma_number(value: Any) -> float | None:
    """Parse ``"27,1451"`` or ``27.1451`` into a finite float."""
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        try:
            value = float(value)
        except ValueError:
            return None
    return finite_number(value)


def split_line_codes(value: Any) -> list[str]:
    """EShot separates route numbers in a stop row with hyphens, not commas."""
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split("-")]
    return [part for part in parts if part]


def parse_gtfs_calendar(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _rows(text):
        service_id = (item.get("service_id") or "").strip()
        if not service_id:
            continue
        row: dict[str, Any] = {"service_id": service_id}
        for day in WEEKDAY_COLUMNS:
            row[day] = _gtfs_bool(item.get(day))
        row["start_date"] = parse_gtfs_date(item.get("start_date"))
        row["end_date"] = parse_gtfs_date(item.get("end_date"))
        rows.append(row)
    return rows


def parse_gtfs_metadata(*, routes: str, trips: str, calendar: str) -> dict[str, Any]:
    """Group GTFS routes/trips/calendar into a bounded per-route summary."""
    service_ids: dict[str, list[str]] = {}
    trip_counts: dict[str, int] = {}
    for item in _rows(trips):
        route_id = (item.get("route_id") or "").strip()
        if not route_id:
            continue
        trip_counts[route_id] = trip_counts.get(route_id, 0) + 1
        service_id = (item.get("service_id") or "").strip()
        if service_id:
            bucket = service_ids.setdefault(route_id, [])
            if service_id not in bucket:
                bucket.append(service_id)

    calendar_rows = parse_gtfs_calendar(calendar)
    windows = [row["end_date"] for row in calendar_rows if row.get("end_date")]
    calendar_end = max(windows) if windows else None

    route_rows: list[dict[str, Any]] = []
    for item in _rows(routes):
        route_id = (item.get("route_id") or "").strip()
        if not route_id:
            continue
        route_rows.append(
            {
                "route_id": route_id,
                "short_name": bounded_text(item.get("route_short_name"), 64),
                "long_name": bounded_text(item.get("route_long_name")),
                "route_type": item.get("route_type"),
                "service_ids": service_ids.get(route_id, []),
                "trips": trip_counts.get(route_id, 0),
                "calendar_start": calendar_rows[0]["start_date"] if calendar_rows else None,
                "calendar_end": calendar_end,
            }
        )
    return {"routes": route_rows, "calendar": calendar_rows, "calendar_end": calendar_end}


class EshotConnector:
    def __init__(self, *, settings: Settings, ckan: CkanClient | None = None):
        self.settings = settings
        self.ckan = ckan or CkanClient(settings)
        self.iztek_base_url = settings.iztek_base_url.rstrip("/")

    async def _datastore_pages(self, resource_id: str) -> list[dict[str, Any]]:
        page_size = self.settings.eshot_datastore_page_size
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.ckan.datastore_search(resource_id=resource_id, limit=page_size, offset=offset)
            records = page.get("records") or []
            if not isinstance(records, list):
                raise SourceError("datastore records were not a list")
            rows.extend(record for record in records if isinstance(record, dict))
            total = page.get("total")
            offset += len(records)
            if not records or not isinstance(total, int) or offset >= total:
                break
        if not rows:
            raise SourceError("EShot datastore returned no rows")
        return rows

    async def stops(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> list[dict[str, Any]]:
            records = await self._datastore_pages(self.settings.eshot_stops_resource_id)
            rows: list[dict[str, Any]] = []
            for item in records:
                lat = finite_number(item.get("ENLEM"))
                lon = finite_number(item.get("BOYLAM"))
                stop_id = str(item.get("DURAK_ID") or "").strip()
                if lat is None or lon is None or not stop_id:
                    continue
                name = (item.get("DURAK_ADI") or "").strip() or None
                rows.append(
                    {
                        "id": bounded_id(stop_id),
                        "name": name,
                        "lat": lat,
                        "lon": lon,
                        "routes": split_line_codes(item.get("DURAKTAN_GECEN_HATLAR")),
                    }
                )
            if not rows:
                raise SourceError("EShot stop list contained no usable rows")
            return rows

        return await cached_source_data(
            "eshot.stops",
            ttl_seconds=self.settings.eshot_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.eshot_stale_if_error_seconds,
            loader=loader,
        )

    async def arrivals(self, stop_id: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        key = f"iztek.arrivals.{stop_id}"

        async def loader() -> list[dict[str, Any]]:
            await _throttle()
            payload = await get_json(
                f"{self.iztek_base_url}/duragayaklasanotobusler/{stop_id}",
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
                strict=True,
            )
            expect_type(payload, list, what="iztek arrivals")
            rows: list[dict[str, Any]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                lat = finite_number(item.get("KoorX"))
                lon = finite_number(item.get("KoorY"))
                rows.append(
                    {
                        "bus_id": item.get("OtobusId"),
                        "line": bounded_text(item.get("HatNumarasi"), 32),
                        "line_name": bounded_text(item.get("HatAdi")),
                        "direction": item.get("HattinYonu"),
                        "stops_remaining": item.get("KalanDurakSayisi"),
                        "lat": lat,
                        "lon": lon,
                        "wheelchair_accessible": item.get("EngelliMi")
                        if isinstance(item.get("EngelliMi"), bool)
                        else None,
                        "bike_rack": item.get("BisikletAparatliMi")
                        if isinstance(item.get("BisikletAparatliMi"), bool)
                        else None,
                    }
                )
            return rows

        return await cached_source_data(
            key,
            ttl_seconds=self.settings.iztek_cache_ttl_seconds,
            loader=loader,
        )

    async def line_positions(self, line: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Live vehicle positions for one line (İZTEK ``hatotobuskonumlari``).

        The source writes coordinates as strings with a comma decimal
        separator (``"38,35391167"``) and names latitude ``KoorX``.
        """
        key = f"iztek.positions.{line}"

        async def loader() -> list[dict[str, Any]]:
            await _throttle()
            payload = await get_json(
                f"{self.iztek_base_url}/hatotobuskonumlari/{line}",
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
                strict=True,
            )
            expect_type(payload, dict, what="iztek line positions")
            if payload.get("HataVarMi") is True:
                raise SourceError("İZTEK reported an error for the line position query")
            rows: list[dict[str, Any]] = []
            for item in payload.get("HatOtobusKonumlari") or []:
                if not isinstance(item, dict):
                    continue
                lat = parse_comma_number(item.get("KoorX"))
                lon = parse_comma_number(item.get("KoorY"))
                if not valid_lat_lon(lat, lon):
                    continue
                rows.append(
                    {
                        "bus_id": item.get("OtobusId"),
                        "line": line,
                        "direction": item.get("Yon"),
                        "lat": lat,
                        "lon": lon,
                    }
                )
            return rows

        return await cached_source_data(
            key,
            ttl_seconds=min(15, int(getattr(self.settings, "iztek_positions_cache_ttl_seconds", 15))),
            loader=loader,
        )

    async def gtfs_archive(self) -> bytes:
        """Download the full GTFS ZIP once for the local timetable build."""
        return await get_zip(
            self.settings.eshot_gtfs_url,
            timeout=self.settings.request_timeout_seconds,
            attempts=self.settings.request_attempts,
            max_bytes=self.settings.eshot_gtfs_max_bytes,
        )

    async def gtfs(self) -> tuple[dict[str, Any], CacheInfo]:
        async def loader() -> dict[str, Any]:
            members = await get_zip_members(
                self.settings.eshot_gtfs_url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.eshot_gtfs_max_bytes,
                max_member_bytes={
                    **GTFS_MEMBERS,
                    "stops.txt": self.settings.eshot_gtfs_member_max_bytes,
                },
                required=("stops.txt", "routes.txt", "trips.txt", "calendar.txt"),
            )
            return parse_gtfs_metadata(
                routes=decode_member(members["routes.txt"], name="routes.txt"),
                trips=decode_member(members["trips.txt"], name="trips.txt"),
                calendar=decode_member(members["calendar.txt"], name="calendar.txt"),
            )

        return await cached_source_data(
            "eshot.gtfs",
            ttl_seconds=self.settings.eshot_gtfs_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.eshot_gtfs_stale_if_error_seconds,
            loader=loader,
        )
