from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.geo import normalize_name
from app.core.validation import InputValidationError

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "places.json"


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    lat: float
    lon: float


class PlaceResolver:
    """Resolve district and neighborhood labels to published reference points."""

    def __init__(self, path: Path | None = None):
        document = json.loads((path or DATA_PATH).read_text(encoding="utf-8"))
        self.source = document.get("source")
        self.license = document.get("license")
        self.precision = document.get("precision")
        self._by_name: dict[str, Place] = {}
        for item in document.get("places", []):
            place = Place(
                name=item["name"],
                kind=item["kind"],
                lat=float(item["lat"]),
                lon=float(item["lon"]),
            )
            self._by_name[normalize_name(place.name)] = place

    def resolve(self, value: str) -> Place:
        key = normalize_name(value)
        place = self._by_name.get(key)
        if place is None:
            for suffix in (", izmir", " izmir"):
                if key.endswith(suffix):
                    place = self._by_name.get(key[: -len(suffix)].strip())
                    if place is not None:
                        break
        if place is None:
            examples = ", ".join(sorted(item.name for item in self._by_name.values())[:8])
            raise InputValidationError(
                f"Unknown place '{value}'. Use coordinates or one of the supported "
                f"district/neighborhood names (for example: {examples}).",
                field="place",
            )
        return place

    def names(self) -> list[str]:
        return sorted(place.name for place in self._by_name.values())
