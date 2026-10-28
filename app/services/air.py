from __future__ import annotations

from typing import Any

from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, success_envelope
from app.core.geo import normalize_name
from app.core.settings import Settings
from app.core.validation import resolve_limit
from app.services import sources
from app.services.sources import is_source_failure, source_failure_envelope


class AirQualityService:
    def __init__(self, *, settings: Settings, api: IzmirOpenApi | None = None):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)

    async def readings(self, *, day: str, station: str | None = None,
                       limit: int | None = None) -> dict[str, Any]:
        safe_limit = resolve_limit(limit, self.settings.max_limit, self.settings.max_limit)
        try:
            stations, info = await self.api.air_quality(day)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            if not is_source_failure(exc):
                raise
            return source_failure_envelope(
                exc,
                summary="Hava kalitesi ölçümleri okunamadı.",
                used=[sources.AIR],
                limits=[f"date={day}"],
            )
        wanted = normalize_name(station) if station else None
        data: list[dict[str, Any]] = []
        for entry in stations:
            if wanted and wanted not in normalize_name(str(entry["station"])):
                continue
            for reading in entry["readings"]:
                data.append(
                    {
                        "station": entry["station"],
                        "station_id": entry["station_id"],
                        "observed_at": entry["observed_at"],
                        "pollutant": reading["pollutant"],
                        "value": reading["value"],
                        "unit": reading["unit"],
                    }
                )
        data.sort(key=lambda row: (row["station"], row["pollutant"] or ""))
        returned = data[:safe_limit]
        return success_envelope(
            summary=(
                f"{len(returned)} hava kalitesi ölçümü listelendi"
                + (f" ({station})." if station else ".")
            ),
            data=returned,
            sources=[sources.AIR],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[
                f"limit={safe_limit}",
                f"date={day}",
                "Kaynak yalnızca istasyon adı ve ölçüm değeri verir; koordinat yoktur.",
            ],
            warnings=[
                "İstenen tarih için kaynak önceki günün ölçümlerini döndürebilir; observed_at alanını esas alın.",
                "Ölçüm birimleri kaynakta belirtilmediği için unit=null bırakıldı.",
            ],
            next_queries=["İstasyon adıyla filtreleyin (örn. Çiğli, Bornova)."],
            matched=len(data),
        )
