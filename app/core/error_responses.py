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
    "lat": ("Supply a WGS84 latitude between -90 and 90.", "lat must be a WGS84 latitude"),
    "lon": ("Supply a WGS84 longitude between -180 and 180.", "lon must be a WGS84 longitude"),
    "radius_m": ("Use a positive radius no larger than max_radius_m.", "radius_m must be positive"),
    "limit": ("Use a positive limit no larger than max_limit.", "limit must be positive"),
    "bbox": (
        "Order the rectangle as min_lon, min_lat, max_lon, max_lat with "
        "min < max on both axes.",
        "bbox must be an ordered rectangle",
    ),
    "types": ("Use only the advertised type names.", "types must come from the advertised list"),
    "kinds": ("Use only the advertised kind names.", "kinds must come from the advertised list"),
    "place": (
        "Use a published district or neighborhood name, or supply lat/lon.",
        "place must resolve to a published reference point",
    ),
    "place_district": (
        "Add place_district only together with place to disambiguate same-named "
        "neighborhoods.",
        "place_district requires place",
    ),
    "district": ("Use an İzmir district name.", "district must be a published İzmir district"),
    "stop_id": (
        "Look the id up with izmir_bus_stops first; ids come from the published "
        "stop list.",
        "stop_id must exist in the published EStop stop list",
    ),
    "resource_id": (
        "Use a DataStore-active resource id from izmir_get_dataset.",
        "resource_id must be an existing DataStore resource",
    ),
    "filters": (
        "Use column names from izmir_get_resource_schema.",
        "filters must use advertised columns",
    ),
    "sort": (
        "Use 'COLUMN' or 'COLUMN asc|desc' with a column from the resource schema.",
        "sort must name an advertised column",
    ),
    "search": ("Keep search text under the advertised length.", "search too long"),
    "day": (
        "Use a Turkish weekday name (pazartesi..pazar), 'bugun' or 'yarin'.",
        "day must be a weekday name",
    ),
    "operator": (
        "Use eshot, metro, izdeniz or izban.",
        "operator must be an advertised operator",
    ),
    "query": ("Use a route code or name that exists in the published table.", "query not found"),
    "line": ("Use a published bus line number.", "line not found"),
    "neighborhood": (
        "Use a neighborhood from the published muhtarlık inventory, optionally "
        "with district.",
        "neighborhood must be published",
    ),
    "kinds|empty": ("Select at least one kind.", "kinds must not be empty"),
}


def _hint(field: str | None, message: str) -> tuple[str, str] | None:
    if not field:
        return None
    if "non-empty" in message or "empty" in message:
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
        summary="Invalid request input.",
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
