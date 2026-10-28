from __future__ import annotations

import re
from datetime import date


class InputValidationError(ValueError):
    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = "validation_error"


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    if not -90 <= lat <= 90:
        raise InputValidationError("lat must be between -90 and 90", field="lat")
    if not -180 <= lon <= 180:
        raise InputValidationError("lon must be between -180 and 180", field="lon")
    return lat, lon


def validate_radius(radius_m: int, max_radius_m: int = 5_000) -> int:
    if radius_m <= 0:
        raise InputValidationError("radius_m must be positive", field="radius_m")
    if radius_m > max_radius_m:
        raise InputValidationError(f"radius_m must be <= {max_radius_m}", field="radius_m")
    return radius_m


def validate_limit(limit: int, max_limit: int = 100) -> int:
    if limit <= 0:
        raise InputValidationError("limit must be positive", field="limit")
    if limit > max_limit:
        raise InputValidationError(f"limit must be <= {max_limit}", field="limit")
    return limit


def resolve_limit(limit: int | None, default_limit: int, max_limit: int = 100) -> int:
    return validate_limit(default_limit if limit is None else limit, max_limit)


def validate_text(value: str, *, field: str, max_length: int, min_length: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_length:
        raise InputValidationError(f"{field} is required", field=field)
    if len(text) > max_length:
        raise InputValidationError(f"{field} must be <= {max_length} characters", field=field)
    return text


def validate_identifier(value: str, *, field: str, max_length: int = 120) -> str:
    text = validate_text(value, field=field, max_length=max_length)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        raise InputValidationError(f"{field} contains unsupported characters", field=field)
    return text


def validate_date(value: str | None) -> str:
    if value is None or not str(value).strip():
        return date.today().isoformat()
    text = validate_text(value, field="date", max_length=10)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InputValidationError("date must use YYYY-MM-DD", field="date") from exc


def validate_filters(filters: dict | None) -> dict | None:
    if filters is None:
        return None
    if not isinstance(filters, dict):
        raise InputValidationError("filters must be an object", field="filters")
    if len(filters) > 10:
        raise InputValidationError("filters must contain <= 10 keys", field="filters")
    safe: dict = {}
    for key, value in filters.items():
        safe_key = validate_text(str(key), field="filters", max_length=80)
        if not re.fullmatch(r"[\w .:-]+", safe_key, flags=re.UNICODE):
            raise InputValidationError("filter key contains unsupported characters", field="filters")
        if isinstance(value, str):
            safe[safe_key] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[safe_key] = value
        elif isinstance(value, list) and len(value) <= 20 and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            safe[safe_key] = value
        else:
            raise InputValidationError("filter values must be scalars or scalar lists", field="filters")
    return safe
