"""Typed error envelopes shared by the MCP handlers.

Two goals: every rejection looks the same shape, and a rejected call tells the
caller *how* to fix it (``error.repair``) instead of only that it failed. The
repair hints are derived from our own schema knowledge; source text is never
copied into them.
"""
from __future__ import annotations

from typing import Any

from app.core.envelope import Repair, Source, error_envelope
from app.core.validation import InputValidationError

# Field-specific guidance. Kept deliberately small and factual: each entry must
# describe a constraint the tool actually enforces.
FIELD_HINTS: dict[str, tuple[str, str]] = {
    "lat": ("-90 ile 90 arasında bir WGS84 enlemi verin.", "lat bir WGS84 enlemi olmalıdır"),
    "lon": ("-180 ile 180 arasında bir WGS84 boylamı verin.", "lon bir WGS84 boylamı olmalıdır"),
    "radius_m": ("max_radius_m sınırını aşmayan pozitif bir yarıçap kullanın.", "radius_m pozitif olmalıdır"),
    "limit": ("max_limit sınırını aşmayan pozitif bir limit kullanın.", "limit pozitif olmalıdır"),
    "bbox": (
        "Dikdörtgeni min_lon, min_lat, max_lon, max_lat sırasıyla ve her eksende "
        "min < max olacak şekilde verin.",
        "bbox sıralı bir dikdörtgen olmalıdır",
    ),
    "types": ("Yalnızca duyurulan tür adlarını kullanın.", "types duyurulan listeden olmalıdır"),
    "kinds": ("Yalnızca duyurulan tür adlarını kullanın.", "kinds duyurulan listeden olmalıdır"),
    "place": (
        "Yayımlanmış bir ilçe veya mahalle adı kullanın ya da lat/lon verin.",
        "place yayımlanmış bir referans noktasına çözümlenmelidir",
    ),
    "place_district": (
        "place_district yalnızca aynı adlı mahalleleri ayırmak için place ile "
        "birlikte verilir.",
        "place_district için place gerekir",
    ),
    "district": ("Bir İzmir ilçe adı kullanın.", "district yayımlanmış bir İzmir ilçesi olmalıdır"),
    "stop_id": (
        "Id'yi önce izmir_bus_stops ile arayın; id'ler yayımlanmış durak "
        "listesinden gelir.",
        "stop_id yayımlanmış EShot durak listesinde bulunmalıdır",
    ),
    "resource_id": (
        "izmir_get_dataset ile dönen DataStore etkin bir kaynak id'si kullanın.",
        "resource_id var olan bir DataStore kaynağı olmalıdır",
    ),
    "filters": (
        "izmir_get_resource_schema ile duyurulan sütun adlarını kullanın.",
        "filters duyurulan sütunları kullanmalıdır",
    ),
    "sql": (
        "records üzerinde tek bir SELECT kullanın; join, alt sorgu, CTE, union, "
        "window veya gelişigüzel fonksiyon kullanılamaz.",
        "sql records üzerinde sınırlı bir SELECT olmalıdır",
    ),
    "sort": (
        "Kaynak şemasındaki bir sütunla 'COLUMN' veya 'COLUMN asc|desc' kullanın.",
        "sort duyurulan bir sütunu adlandırmalıdır",
    ),
    "search": ("Arama metnini duyurulan uzunluğun altında tutun.", "search çok uzun"),
    "day": (
        "Bir Türkçe hafta günü (pazartesi..pazar), 'bugun' veya 'yarin' kullanın.",
        "day bir hafta günü olmalıdır",
    ),
    "operator": (
        "eshot, metro, izdeniz veya izban kullanın.",
        "operator duyurulan operatörlerden biri olmalıdır",
    ),
    "query": ("Yayımlanmış tabloda var olan bir hat kodu veya adı kullanın.", "query bulunamadı"),
    "line": ("Yayımlanmış bir otobüs hat numarası kullanın.", "line bulunamadı"),
    "neighborhood": (
        "Yayımlanmış muhtarlık envanterinden bir mahalle, isteğe bağlı olarak "
        "district ile birlikte kullanın.",
        "neighborhood yayımlanmış olmalıdır",
    ),
    "kinds|empty": ("En az bir tür seçin.", "kinds boş olamaz"),
}


def _hint(field: str | None, message: str) -> tuple[str, str] | None:
    if not field:
        return None
    if "non-empty" in message or "empty" in message or "boş" in message:
        return FIELD_HINTS.get(f"{field}|empty") or FIELD_HINTS.get(field)
    return FIELD_HINTS.get(field)


def validation_error_envelope(
    exc: InputValidationError,
    *,
    sources: list[Source] | None = None,
    tool: str | None = None,
    limits: list[str] | None = None,
) -> dict[str, Any]:
    """Build a ``validation_error`` envelope with a structured repair hint."""
    message = str(exc)
    hint = _hint(exc.field, message)
    repair: Repair | None = None
    if hint is not None:
        next_step, constraint = hint
        repair = Repair(
            next_step=next_step,
            tool=tool,
            arguments=None,
            constraint=constraint,
        )
    return error_envelope(
        summary="Geçersiz istek girdisi.",
        warning=message,
        code="validation_error",
        field=exc.field,
        sources=sources or [],
        limits=limits or [],
        repair=repair,
        next_step=repair.next_step if repair else None,
    )


def source_error_envelope(
    exc: BaseException,
    *,
    summary: str,
    sources: list[Source] | None = None,
    limits: list[str] | None = None,
    code: str | None = None,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    """Typed source failure; ``temporary`` follows from the code."""
    from app.services.sources import source_failure_envelope

    payload = source_failure_envelope(exc, summary=summary, used=sources or [], limits=limits)
    if code or retry_after_ms is not None:
        payload["error"] = {
            **payload["error"],
            **({"code": code} if code else {}),
            **({"retry_after_ms": retry_after_ms} if retry_after_ms is not None else {}),
        }
    return payload
