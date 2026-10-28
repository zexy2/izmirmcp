from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_serializer

FreshnessStatus = Literal["fresh", "stale", "unknown", "broken"]

MACHINE_HOST_MARKERS = ("api", "proxy")
MACHINE_PATH_SEGMENTS = frozenset({"api", "download", "docs"})
MACHINE_FILE_SUFFIXES = (
    ".asmx", ".csv", ".geojson", ".json", ".xls", ".xlsx", ".xml", ".zip",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_page_url(url: str | None) -> str | None:
    """Return a citable human page URL, never an API or file endpoint."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    segments = [segment.lower() for segment in parts.path.split("/") if segment]
    if parts.scheme != "https" or not host:
        return None
    if any(marker in label for label in host.split(".") for marker in MACHINE_HOST_MARKERS):
        return None
    if MACHINE_PATH_SEGMENTS.intersection(segments):
        return None
    if segments and segments[-1].endswith(MACHINE_FILE_SUFFIXES):
        return None
    return url


class Freshness(BaseModel):
    status: FreshnessStatus
    retrieved_at: str = Field(default_factory=utc_now_iso)
    source_updated_at: str | None = None
    ttl_seconds: int | None = None


class Source(BaseModel):
    name: str
    publisher: str = "İzmir Büyükşehir Belediyesi"
    url: str | None = Field(
        default=None,
        description=(
            "Human-readable source page for citations; null when the source is "
            "only an API endpoint or data file."
        ),
    )
    license: str | None = None
    dataset_id: str | None = None
    resource_id: str | None = None
    scope: str | None = None
    source_updated_at: str | None = None

    @field_serializer("url")
    def _serialize_url(self, url: str | None) -> str | None:
        return public_page_url(url)


class ErrorInfo(BaseModel):
    code: str
    temporary: bool = False
    field: str | None = None
    next_step: str | None = None


class ResultInfo(BaseModel):
    returned: int = Field(ge=0)
    matched: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    scope: str = "data"
    next_step: str | None = None


def result_info(
    *, returned: int, matched: int | None = None,
    truncated: bool | None = None, scope: str = "data",
) -> ResultInfo:
    if truncated is None and matched is not None:
        truncated = matched > returned
    note = None
    if truncated:
        note = "Increase limit within the advertised maximum or narrow the filters. This is not a complete total."
    elif truncated is None:
        note = "Completeness is unknown; inspect source coverage, limits and warnings."
    return ResultInfo(returned=returned, matched=matched, truncated=truncated, scope=scope, next_step=note)


class ResponseEnvelope(BaseModel):
    ok: bool = True
    summary: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    freshness: Freshness
    sources: list[Source] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_queries: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    result_info: ResultInfo | None = None


def success_envelope(
    *,
    summary: str,
    data: list[dict[str, Any]] | None = None,
    sources: list[Source] | None = None,
    freshness: Freshness | None = None,
    limits: list[str] | None = None,
    warnings: list[str] | None = None,
    next_queries: list[str] | None = None,
    matched: int | None = None,
    result: ResultInfo | None = None,
) -> dict[str, Any]:
    if result is None:
        result = result_info(returned=len(data or []), matched=matched)
    envelope = ResponseEnvelope(
        summary=summary,
        data=data or [],
        sources=sources or [],
        freshness=freshness or Freshness(status="unknown"),
        limits=limits or [],
        warnings=warnings or [],
        next_queries=next_queries or [],
        result_info=result,
    )
    return envelope.model_dump(mode="json")


def error_envelope(
    *,
    summary: str,
    warning: str,
    sources: list[Source] | None = None,
    freshness_status: FreshnessStatus = "broken",
    data: list[dict[str, Any]] | None = None,
    limits: list[str] | None = None,
    code: str | None = None,
    temporary: bool | None = None,
    field: str | None = None,
    next_step: str | None = None,
) -> dict[str, Any]:
    code = code or "request_failed"
    if temporary is None:
        temporary = code in {
            "source_unavailable", "source_rate_limited", "source_timeout",
        }
    if next_step is None:
        next_step = (
            "Retry later; source availability is not guaranteed."
            if temporary
            else "Review the inputs and advertised tool limits before retrying."
        )
    envelope = ResponseEnvelope(
        ok=False,
        summary=summary,
        data=data or [],
        freshness=Freshness(status=freshness_status),
        sources=sources or [],
        limits=limits or [],
        warnings=[warning],
        error=ErrorInfo(code=code, temporary=temporary, field=field, next_step=next_step),
        result_info=result_info(returned=len(data or []), scope="error_details"),
    )
    return envelope.model_dump(mode="json")


def finite_number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
