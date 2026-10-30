from __future__ import annotations

import csv
import io
from datetime import date as date_cls
from typing import Any
from urllib.parse import urlencode

from app.connectors.http import get_json, get_text
from app.connectors.schema import SchemaDriftError
from app.core.envelope import finite_number
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data

DEFAULT_IZSU_API_BASE_URL = "https://izsu.gov.tr/api/proxy"
# A published past day does not change; today's figures may still be revised.
DEFAULT_IZSU_PAST_CACHE_TTL_SECONDS = 7 * 86_400


class IzsuClient:
    """İZSU dam levels.

    Primary source is the izsu.gov.tr ``DamWaterStatus/WithInfoList`` JSON
    (date-addressable, verified live 2026-10-29); the published semicolon CSV
    is kept as fallback. The openapi ``/izsu/barajdurum`` and
    ``/izsu/arizakaynaklisukesintileri`` endpoints returned HTTP 500 during
    verification and are not used.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def _api_base(self) -> str:
        base = getattr(self.settings, "izsu_api_base_url", None) or DEFAULT_IZSU_API_BASE_URL
        return base.rstrip("/")

    def _ttl_for(self, day: str) -> int:
        if day < date_cls.today().isoformat():
            return int(
                getattr(self.settings, "izsu_past_cache_ttl_seconds", None) or DEFAULT_IZSU_PAST_CACHE_TTL_SECONDS
            )
        return self.settings.izsu_cache_ttl_seconds

    async def dam_status(self, day: str) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Dam rows for ``day`` (YYYY-MM-DD) from the İZSU JSON API."""
        url = f"{self._api_base()}/DamWaterStatus/WithInfoList?{urlencode({'date': day})}"

        async def loader() -> tuple[list[dict[str, Any]], str | None]:
            payload = await get_json(
                url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
            )
            rows = parse_dam_json(payload)
            updated = max((row["observed_at"] for row in rows if row["observed_at"]), default=None)
            return rows, updated

        return await cached_source_data(
            f"izsu.dam_status.{day}",
            ttl_seconds=self._ttl_for(day),
            stale_if_error_seconds=self.settings.izsu_stale_if_error_seconds,
            loader=loader,
            max_entries=64,
        )

    async def dams(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        """Today's dams: JSON first (CSV coordinates merged in), CSV fallback."""
        try:
            rows, info = await self.dam_status(date_cls.today().isoformat())
            if not rows:
                raise ValueError("İZSU JSON returned no rows for today")
        except Exception:  # noqa: BLE001 - any JSON failure falls back to the CSV
            return await self.dams_csv()
        try:
            csv_rows, _ = await self.dams_csv()
        except Exception:  # noqa: BLE001 - coordinates are best effort
            csv_rows = []
        return merge_csv_coordinates(rows, csv_rows), info

    async def dams_csv(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> tuple[list[dict[str, Any]], str | None]:
            text = await get_text(
                self.settings.izsu_dams_csv_url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
                strict=True,
            )
            rows = parse_dam_csv(text)
            if not rows:
                raise ValueError("İZSU dam CSV contained no usable rows")
            updated = max((row["observed_at"] for row in rows if row["observed_at"]), default=None)
            return rows, updated

        return await cached_source_data(
            "izsu.dams",
            ttl_seconds=self.settings.izsu_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.izsu_stale_if_error_seconds,
            loader=loader,
        )


def turkish_fold(value: str) -> str:
    """Casefold with Turkish dotted/dotless I rules (İ→i, I→ı)."""
    return str(value).replace("İ", "i").replace("I", "ı").casefold().strip()


def parse_dam_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    header = set(reader.fieldnames or [])
    if text.strip() and not {"BARAJ_KUYU_ADI", "DOLULUK_ORANI"} <= header:
        raise SchemaDriftError("İZSU dam CSV is missing required columns")
    rows: list[dict[str, Any]] = []
    for item in reader:
        name = (item.get("BARAJ_KUYU_ADI") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "id": item.get("BARAJ_KUYU_ID"),
                "name": name,
                "observed_at": item.get("DURUM_TARIHI"),
                "occupancy_percent": finite_number(item.get("DOLULUK_ORANI")),
                # SU_YUKSEKLIGI mirrors DOLULUK_ORANI (a percentage) in the published
                # CSV, so it is not a real level; never surface it as one.
                "water_level": None,
                "usable_capacity_m3": finite_number(item.get("TUKETILEBILIR_SU_KAPASITESI")),
                "max_capacity_m3": finite_number(item.get("MAKSIMUM_SU_KAPASITESI")),
                "max_water_level": finite_number(item.get("MAKSIMUM_SU_YUKSEKLIGI")),
                "lat": finite_number(item.get("ENLEM")),
                "lon": finite_number(item.get("BOYLAM")),
                "usable_lake_volume_m3": finite_number(item.get("KULLANILABILIR_GOL_SU_HACMI")),
            }
        )
    return rows


def parse_dam_json(payload: Any) -> list[dict[str, Any]]:
    """Normalise ``DamWaterStatus/WithInfoList`` into the CSV row shape plus extras."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SchemaDriftError("İZSU DamWaterStatus response has no data[] list")
    rows: list[dict[str, Any]] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        facility = item.get("damWellFacility")
        if not isinstance(facility, dict):
            facility = {}
        name = str(facility.get("name") or "").strip()
        if not name:
            continue
        rows.append(
            {
                "id": facility.get("id") or item.get("id"),
                "name": name,
                "observed_at": item.get("date"),
                "occupancy_percent": finite_number(item.get("occupancyRate")),
                "water_level": finite_number(item.get("waterLevel")),
                "usable_capacity_m3": finite_number(item.get("usableWaterStatus")),
                "max_capacity_m3": finite_number(item.get("maximumWaterCapacity")),
                "max_water_level": finite_number(item.get("maximumWaterLevel")),
                "lat": None,
                "lon": None,
                "usable_lake_volume_m3": None,
                "water_volume_m3": finite_number(item.get("waterStatus")),
                "min_capacity_m3": finite_number(item.get("minimumWaterCapacity")),
                "min_water_level": finite_number(item.get("minimumWaterLevel")),
                "usable_water_capacity_m3": finite_number(item.get("usableWaterCapacity")),
            }
        )
    return rows


def merge_csv_coordinates(rows: list[dict[str, Any]], csv_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill JSON rows' missing coordinates from the CSV, matched by folded name."""
    by_name = {turkish_fold(row["name"]): row for row in csv_rows}
    merged: list[dict[str, Any]] = []
    for row in rows:
        out = dict(row)
        extra = by_name.get(turkish_fold(row["name"]))
        if extra:
            for key in ("lat", "lon", "usable_lake_volume_m3"):
                if out.get(key) is None:
                    out[key] = extra.get(key)
        merged.append(out)
    return merged
