from __future__ import annotations

from typing import Any

from app.connectors.izmir_api import IzmirOpenApi
from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import Settings
from app.core.validation import InputValidationError, resolve_limit
from app.services import sources
from app.services.sources import is_source_failure, source_failure_envelope

MODES = ("metro", "izban", "izdeniz")


class TransitService:
    def __init__(self, *, settings: Settings, api: IzmirOpenApi | None = None):
        self.settings = settings
        self.api = api or IzmirOpenApi(settings)

    async def stations(self, *, mode: str, limit: int | None = None) -> dict[str, Any]:
        if mode not in MODES:
            raise InputValidationError("mode metro, izban veya izdeniz olmalıdır", field="mode")
        safe_limit = resolve_limit(limit, self.settings.max_limit, self.settings.max_limit)
        sources_by_mode = {"metro": sources.METRO, "izban": sources.IZBAN, "izdeniz": sources.FERRY}
        try:
            if mode == "metro":
                rows, info = await self.api.metro_stations()
            elif mode == "izban":
                rows, info = await self.api.izban_stations()
            else:
                rows, info = await self.api.ferry_piers()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            if not is_source_failure(exc):
                raise
            return source_failure_envelope(
                exc,
                summary=f"{mode} istasyon listesi okunamadı.",
                used=[sources_by_mode[mode]],
                limits=[f"mode={mode}"],
            )
        source = sources_by_mode[mode]
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
            raise InputValidationError("mode metro, izban veya izdeniz olmalıdır", field="mode")
        if not 1 <= day <= 7:
            raise InputValidationError("day 1 ile 7 arasında olmalıdır (kaynağın gün kimliği)", field="day")

        if mode == "metro":
            if any(value is not None for value in (from_id, to_id, pier_id)):
                raise InputValidationError(
                    "metro tarifesi şehir geneli sıklık tablosudur; from_id, to_id ve pier_id desteklenmez",
                    field="from_id",
                )
            try:
                rows, info = await self.api.metro_schedule()
            except Exception as exc:  # noqa: BLE001 - never leak a source failure
                return self._fetch_failure(
                    exc, "metro sefer tarifesi okunamadı.", sources.TRANSIT_METRO, [f"mode={mode}"]
                )
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
                raise InputValidationError("izban için from_id ve to_id gerekir", field="from_id")
            if pier_id is not None:
                raise InputValidationError("pier_id yalnızca izdeniz içindir", field="pier_id")
            try:
                rows, info = await self.api.izban_schedule(from_id, to_id)
            except Exception as exc:  # noqa: BLE001 - never leak a source failure
                return self._fetch_failure(
                    exc,
                    "İZBAN sefer tarifesi okunamadı.",
                    sources.TRANSIT_IZBAN,
                    [f"from_id={from_id}", f"to_id={to_id}"],
                )
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
                "izdeniz için pier_id ya da from_id/to_id ikilisinden birini kullanın", field="pier_id"
            )
        if pier_id is not None:
            try:
                payload, info = await self.api.izdeniz_pier_schedule(pier_id, day)
            except Exception as exc:  # noqa: BLE001 - never leak a source failure
                return self._fetch_failure(
                    exc,
                    "İZDENİZ iskele tarifesi okunamadı.",
                    sources.TRANSIT_FERRY,
                    [f"pier_id={pier_id}", f"day={day}"],
                )
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
            raise InputValidationError("izdeniz için pier_id ya da from_id ile to_id birlikte gerekir", field="pier_id")
        try:
            rows, info = await self.api.izdeniz_route_schedule(from_id, to_id, day)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return self._fetch_failure(
                exc,
                "İZDENİZ hat tarifesi okunamadı.",
                sources.TRANSIT_FERRY,
                [f"from_id={from_id}", f"to_id={to_id}", f"day={day}"],
            )
        return self._response(
            mode=mode,
            rows=rows,
            info=info,
            source=sources.TRANSIT_FERRY,
            summary=f"{len(rows)} İZDENİZ hattı listelendi ({from_id} → {to_id}, gün {day}).",
            limits=[f"from_id={from_id}", f"to_id={to_id}", f"day={day}"],
        )

    async def tram_lines(self) -> dict[str, Any]:
        try:
            rows, info = await self.api.tram_lines()
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return self._fetch_failure(exc, "Tramvay hat listesi okunamadı.", sources.TRANSIT_TRAM, [])
        return success_envelope(
            summary=f"{len(rows)} tramvay hattı/yönü listelendi.",
            data=rows,
            sources=[sources.TRANSIT_TRAM],
            freshness=Freshness(
                status=info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=["line_id kaynağın HatId değeridir; her yön ayrı satırdır."],
            warnings=["Yayımlanmış hat listesidir; canlı sefer durumu değildir."],
            next_queries=["Durak ve sefer sıklığı için izmir_tram_schedule(line_id=<line_id>) kullanın."],
            matched=len(rows),
        )

    async def tram_schedule(self, *, line_id: int) -> dict[str, Any]:
        if isinstance(line_id, bool) or not isinstance(line_id, int) or not 1 <= line_id <= 999:
            raise InputValidationError("line_id 1 ile 999 arasında bir tamsayı olmalıdır", field="line_id")
        limits = [f"line_id={line_id}"]
        try:
            stations, station_info = await self.api.tram_stations(line_id)
            frequency, info = await self.api.tram_schedule(line_id)
        except Exception as exc:  # noqa: BLE001 - never leak a source failure
            return self._fetch_failure(exc, "Tramvay sefer bilgisi okunamadı.", sources.TRANSIT_TRAM, limits)
        warnings = [
            "Yayımlanmış tarifedir; canlı kalkış, gecikme veya varış garantisi değildir.",
        ]
        if not stations and not frequency:
            warnings.append(
                "Kaynak bu line_id için veri döndürmedi; izmir_tram_lines ile geçerli kimlikleri kontrol edin."
            )
        return success_envelope(
            summary=(f"Tramvay hattı {line_id}: {len(stations)} istasyon, {len(frequency)} sefer sıklığı dilimi."),
            data=[{"line_id": line_id, "stations": stations, "frequency": frequency}],
            sources=[sources.TRANSIT_TRAM],
            freshness=Freshness(
                status="stale" if "stale" in (info.status, station_info.status) else info.status,
                ttl_seconds=self.settings.openapi_cache_ttl_seconds,
                source_updated_at=info.source_updated_at,
            ),
            limits=[*limits, "Sıklık saat aralığı ve dakika cinsinden sefer aralığıdır."],
            warnings=warnings,
        )

    @staticmethod
    def _fetch_failure(exc: BaseException, summary: str, source: Source, limits: list[str]):
        """Typed envelope for a connector failure; programming bugs re-raise."""
        if not is_source_failure(exc):
            raise exc
        return source_failure_envelope(exc, summary=summary, used=[source], limits=limits)

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
