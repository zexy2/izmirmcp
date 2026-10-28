from __future__ import annotations

from typing import Any

from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources

MODES = ("metro", "izban", "izdeniz")


class TransitService:
    def __init__(self, *, settings: Settings, api: IzmirOpenApi | None = None):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)

    async def stations(self, *, mode: str, limit: int | None = None) -> dict[str, Any]:
        if mode not in MODES:
            raise InputValidationError("mode must be metro, izban or izdeniz", field="mode")
        safe_limit = resolve_limit(limit, self.settings.max_limit, self.settings.max_limit)
        if mode == "metro":
            rows, info, source = (*await self.api.metro_stations(), sources.METRO)
        elif mode == "izban":
            rows, info, source = (*await self.api.izban_stations(), sources.IZBAN)
        else:
            rows, info, source = (*await self.api.ferry_piers(), sources.FERRY)
        data = rows[:safe_limit]
        return success_envelope(
            summary=f"{len(data)} {mode} istasyonu/iskelesi listelendi.",
            data=data,
            sources=[source],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[f"limit={safe_limit}", f"mode={mode}"],
            warnings=["Konumlar yayımlanmış istasyon listesidir; canlı sefer durumu değildir."],
            matched=len(rows),
        )

    async def schedule(
        self,
        *,
        mode: str,
        from_id: int | None = None,
        to_id: int | None = None,
        pier_id: int | None = None,
        day: int = 1,
    ) -> dict[str, Any]:
        if mode not in MODES:
            raise InputValidationError("mode must be metro, izban or izdeniz", field="mode")
        if not 1 <= day <= 7:
            raise InputValidationError("day must be between 1 and 7 (source day id)", field="day")

        if mode == "metro":
            if any(value is not None for value in (from_id, to_id, pier_id)):
                raise InputValidationError(
                    "metro schedule is a city-wide frequency table; from_id, to_id and pier_id are not supported",
                    field="from_id",
                )
            rows, info = await self.api.metro_schedule()
            return self._response(
                mode=mode,
                rows=rows,
                info=info,
                source=sources.TRANSIT_METRO,
                summary=f"{len(rows)} metro sefer sıklığı dilimi listelendi.",
                limits=["Kaynak istasyon çifti değil, saat aralığı ve sefer aralığı verir."],
            )

        if mode == "izban":
            if from_id is None or to_id is None:
                raise InputValidationError("izban requires from_id and to_id", field="from_id")
            if pier_id is not None:
                raise InputValidationError("pier_id is only for izdeniz", field="pier_id")
            rows, info = await self.api.izban_schedule(from_id, to_id)
            return self._response(
                mode=mode,
                rows=rows,
                info=info,
                source=sources.TRANSIT_IZBAN,
                summary=f"{len(rows)} İZBAN seferi listelendi ({from_id} → {to_id}).",
                limits=[f"from_id={from_id}", f"to_id={to_id}"],
            )

        if pier_id is not None and (from_id is not None or to_id is not None):
            raise InputValidationError(
                "use either pier_id or from_id/to_id for izdeniz", field="pier_id"
            )
        if pier_id is not None:
            payload, info = await self.api.izdeniz_pier_schedule(pier_id, day)
            departures = payload.get("departures", [])
            return self._response(
                mode=mode,
                rows=departures,
                info=info,
                source=sources.TRANSIT_FERRY,
                summary=f"{len(departures)} İZDENİZ kalkışı listelendi (iskele {pier_id}, gün {day}).",
                limits=[f"pier_id={pier_id}", f"day={day}"],
            )
        if from_id is None or to_id is None:
            raise InputValidationError(
                "izdeniz requires pier_id or both from_id and to_id", field="pier_id"
            )
        rows, info = await self.api.izdeniz_route_schedule(from_id, to_id, day)
        return self._response(
            mode=mode,
            rows=rows,
            info=info,
            source=sources.TRANSIT_FERRY,
            summary=f"{len(rows)} İZDENİZ hattı listelendi ({from_id} → {to_id}, gün {day}).",
            limits=[f"from_id={from_id}", f"to_id={to_id}", f"day={day}"],
        )

    def _response(
        self,
        *,
        mode: str,
        rows: list[dict[str, Any]],
        info,
        source,
        summary: str,
        limits: list[str],
    ) -> dict[str, Any]:
        return success_envelope(
            summary=summary,
            data=rows,
            sources=[source],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[f"mode={mode}", *limits],
            warnings=[
                "Yayımlanmış tarifedir; canlı kalkış, gecikme veya varış garantisi değildir.",
                "Gün kimliği kaynağın kendi numarasıdır; haftanın günü olduğu varsayılmamalıdır.",
            ],
        )
