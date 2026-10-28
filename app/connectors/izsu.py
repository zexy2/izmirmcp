from __future__ import annotations

import csv
import io
from typing import Any

from app.connectors.http import get_text
from app.core.envelope import finite_number
from app.core.settings import Settings
from app.core.source_cache import CacheInfo, cached_source_data


class IzsuClient:
    """İZSU dam levels from the published semicolon-delimited CSV.

    The İZSU JSON endpoints (``/izsu/barajdurum`` and
    ``/izsu/arizakaynaklisukesintileri``) returned HTTP 500 during verification,
    so this client deliberately uses the published file instead.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def dams(self) -> tuple[list[dict[str, Any]], CacheInfo]:
        async def loader() -> tuple[list[dict[str, Any]], str | None]:
            text = await get_text(
                self.settings.izsu_dams_csv_url,
                timeout=self.settings.request_timeout_seconds,
                attempts=self.settings.request_attempts,
                max_bytes=self.settings.response_max_bytes,
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


def parse_dam_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
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
                "water_level": finite_number(item.get("SU_YUKSEKLIGI")),
                "usable_capacity_m3": finite_number(item.get("TUKETILEBILIR_SU_KAPASITESI")),
                "max_capacity_m3": finite_number(item.get("MAKSIMUM_SU_KAPASITESI")),
                "max_water_level": finite_number(item.get("MAKSIMUM_SU_YUKSEKLIGI")),
                "lat": finite_number(item.get("ENLEM")),
                "lon": finite_number(item.get("BOYLAM")),
                "usable_lake_volume_m3": finite_number(item.get("KULLANILABILIR_GOL_SU_HACMI")),
            }
        )
    return rows
