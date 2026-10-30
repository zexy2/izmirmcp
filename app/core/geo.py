from __future__ import annotations

import math
import re

EARTH_RADIUS_M = 6_371_008.8

# İzmir province bounding box (south, west, north, east). Used only to say that
# a coordinate cannot possibly match city data — never to reject a query.
IZMIR_BOUNDS = (37.7, 26.0, 39.6, 28.6)

TURKISH_ASCII = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        "Ç": "c",
        "Ğ": "g",
        "İ": "i",
        "I": "i",
        "Ö": "o",
        "Ş": "s",
        "Ü": "u",
    }
)


TR_UPPER = "ABCDEFGHIİJKLMNOPQRSTUVWXYZÇĞÖŞÜ"
TR_LOWER = "abcdefghıijklmnopqrstuvwxyzçğöşü"


def turkish_title(text: str | None) -> str | None:
    """Title-case a published (usually ALL-CAPS) Turkish name.

    ``str.title()`` turns "İPEK" into "İpek" but "ipek" into "İpek" with a
    combining dot when the source uses ``i``/``İ`` inconsistently, so the
    mapping is done explicitly.
    """
    if not text:
        return None
    upper = str.maketrans(TR_LOWER, TR_UPPER)
    words = []
    for word in str(text).split():
        lowered = word.translate(str.maketrans(TR_UPPER, TR_LOWER))
        # Capitalise the first letter of the word and of any segment after a
        # separator, so "1.KADRİYE" becomes "1.Kadriye", not "1.kadriye".
        chars = []
        start = True
        for char in lowered:
            if start and char.isalpha():
                chars.append(char.translate(upper))
                start = False
            else:
                chars.append(char)
                if char in ". -/'":
                    start = True
        words.append("".join(chars))
    return " ".join(words) or None


def normalize_name(value: str) -> str:
    """Casefold and ASCII-fold a Turkish place name for matching."""
    return " ".join(value.translate(TURKISH_ASCII).casefold().split())


def outside_izmir(lat: float, lon: float) -> bool:
    """True when a WGS84 point is outside İzmir province.

    A rectangle is accepted anywhere (shape-only validation), but a point query
    outside the province cannot match any İzmir layer. Answering empty without
    contacting a source keeps that answer deterministic and avoids a needless
    upstream call.
    """
    south, west, north, east = IZMIR_BOUNDS
    return not (south <= lat <= north and west <= lon <= east)


def in_bbox(lat: float, lon: float, *, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> bool:
    """Return whether a point is inside a rectangle, edges included."""
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def has_name_token(value: str | None, name: str) -> bool:
    """Match a full normalized word, never a substring.

    Used for published district/region text such as ``KARŞIYAKA 4``: the label
    must contain the district as its own token, so ``Konak`` does not match
    ``Konaklı``.
    """
    wanted = normalize_name(name)
    if not wanted:
        return False
    tokens = re.findall(r"[a-z0-9]+", normalize_name(str(value or "")))
    return wanted in tokens


def valid_lat_lon(lat: float | None, lon: float | None) -> bool:
    """True only for a finite, in-range coordinate pair.

    Connectors use this to drop source rows that carry a number shaped like a
    coordinate but impossible as one (latitude 999). Skipping is honest: such a
    row can never be placed on a map or matched by a radius query.
    """
    for value, low, high in ((lat, -90.0, 90.0), (lon, -180.0, 180.0)):
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if not math.isfinite(value) or not low <= value <= high:
            return False
    return True


def maps_url(lat: float, lon: float) -> str:
    """Return the map link used by every layer that publishes a coordinate."""
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle metres between two WGS84 points.

    Every argument must be a finite in-range coordinate. A ``NaN`` input used to
    travel silently through the trigonometry and come back as a plausible-but
    invented distance (~half the globe), and ``inf`` raised a bare ``ValueError``
    from ``math``. Both are programming/data errors, so they are rejected up
    front with one clear exception rather than producing a number nobody can
    trust.
    """
    for name, value, low, high in (
        ("lat1", lat1, -90.0, 90.0),
        ("lon1", lon1, -180.0, 180.0),
        ("lat2", lat2, -90.0, 90.0),
        ("lon2", lon2, -180.0, 180.0),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a))), 1)
