from __future__ import annotations

import math
import re
from datetime import date


class InputValidationError(ValueError):
    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = "validation_error"


def _require_number(value: object, *, field: str) -> None:
    """Reject booleans before comparing numbers.

    ``True`` is an ``int`` in Python, so ``-90 <= True <= 90`` passes and a
    caller sending ``{"lat": true}`` silently gets latitude 1.0. Booleans are
    never a coordinate, radius or limit.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputValidationError(f"{field} sayı olmalıdır", field=field)


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    _require_number(lat, field="lat")
    _require_number(lon, field="lon")
    if not -90 <= lat <= 90:
        raise InputValidationError("lat -90 ile 90 arasında olmalıdır", field="lat")
    if not -180 <= lon <= 180:
        raise InputValidationError("lon -180 ile 180 arasında olmalıdır", field="lon")
    return lat, lon


def validate_bbox(bbox: list[float] | tuple[float, ...]) -> tuple[float, float, float, float]:
    """Validate ``min_lon, min_lat, max_lon, max_lat`` and return finite floats.

    A zero-width or zero-height rectangle is rejected: it is not a queryable
    area, and silently treating it as a point would imply precision that a
    rectangle query does not have.
    """
    try:
        values = tuple(float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            "bbox dört sonlu sayı içermelidir: min_lon, min_lat, max_lon, max_lat",
            field="bbox",
        ) from exc
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise InputValidationError(
            "bbox dört sonlu sayı içermelidir: min_lon, min_lat, max_lon, max_lat",
            field="bbox",
        )
    min_lon, min_lat, max_lon, max_lat = values
    validate_lat_lon(min_lat, min_lon)
    validate_lat_lon(max_lat, max_lon)
    if min_lon >= max_lon:
        raise InputValidationError("bbox min_lon, max_lon'dan küçük olmalıdır", field="bbox")
    if min_lat >= max_lat:
        raise InputValidationError("bbox min_lat, max_lat'tan küçük olmalıdır", field="bbox")
    return min_lon, min_lat, max_lon, max_lat


def validate_radius(radius_m: int, max_radius_m: int = 5_000) -> int:
    _require_number(radius_m, field="radius_m")
    if radius_m <= 0:
        raise InputValidationError("radius_m pozitif olmalıdır", field="radius_m")
    if radius_m > max_radius_m:
        raise InputValidationError(f"radius_m en fazla {max_radius_m} olabilir", field="radius_m")
    return radius_m


def validate_limit(limit: int, max_limit: int = 100) -> int:
    _require_number(limit, field="limit")
    if limit <= 0:
        raise InputValidationError("limit pozitif olmalıdır", field="limit")
    if limit > max_limit:
        raise InputValidationError(f"limit en fazla {max_limit} olabilir", field="limit")
    return limit


def resolve_limit(limit: int | None, default_limit: int, max_limit: int = 100) -> int:
    return validate_limit(default_limit if limit is None else limit, max_limit)


def validate_text(value: str, *, field: str, max_length: int, min_length: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_length:
        raise InputValidationError(f"{field} zorunludur", field=field)
    if len(text) > max_length:
        raise InputValidationError(f"{field} en fazla {max_length} karakter olabilir", field=field)
    return text


def validate_identifier(value: str, *, field: str, max_length: int = 120) -> str:
    text = validate_text(value, field=field, max_length=max_length)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        raise InputValidationError(f"{field} desteklenmeyen karakter içeriyor", field=field)
    return text


def validate_date(value: str | None) -> str:
    if value is None or not str(value).strip():
        return date.today().isoformat()
    text = validate_text(value, field="date", max_length=10)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise InputValidationError("date YYYY-MM-DD biçiminde olmalıdır", field="date") from exc


def validate_filters(filters: dict | None) -> dict | None:
    if filters is None:
        return None
    if not isinstance(filters, dict):
        raise InputValidationError("filters bir nesne olmalıdır", field="filters")
    if len(filters) > 10:
        raise InputValidationError("filters en fazla 10 anahtar içerebilir", field="filters")
    safe: dict = {}
    for key, value in filters.items():
        safe_key = validate_text(str(key), field="filters", max_length=80)
        if not re.fullmatch(r"[\w .:-]+", safe_key, flags=re.UNICODE):
            raise InputValidationError("filtre anahtarı desteklenmeyen karakter içeriyor", field="filters")
        if isinstance(value, str):
            safe[safe_key] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[safe_key] = value
        elif isinstance(value, list) and len(value) <= 20 and all(
            isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            safe[safe_key] = value
        else:
            raise InputValidationError("filtre değerleri skaler ya da skaler listeler olmalıdır", field="filters")
    return safe


SORT_PATTERN = re.compile(r"\A([A-Za-z0-9_ .ÇĞİÖŞÜçğıöşü-]{1,80})(?:\s+(asc|desc))?\Z", re.IGNORECASE)


def validate_search(value: str | None, *, max_length: int = 200) -> str | None:
    """Validate a free-text DataStore ``q`` argument.

    The server treats ``q`` as text, never SQL, but the value still ends up in a
    query string; control characters and absurd lengths are rejected here.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if len(text) > max_length:
        raise InputValidationError(f"search en fazla {max_length} karakter olabilir", field="search")
    if any(ord(char) < 32 for char in text):
        raise InputValidationError("search kontrol karakteri içeriyor", field="search")
    return text


def validate_sort(value: str | None) -> str | None:
    """Allow ``COLUMN`` or ``COLUMN asc|desc`` only.

    Only the *shape* is validated here; the column name is checked against the
    resource schema by the service so an unknown column is a clear, local error.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    match = SORT_PATTERN.fullmatch(text)
    if match is None:
        raise InputValidationError(
            "sort 'column' veya 'column asc|desc' biçiminde düz bir sütun adı olmalıdır",
            field="sort",
        )
    column, direction = match.group(1).strip(), (match.group(2) or "").lower()
    return f"{column} {direction}".strip()
