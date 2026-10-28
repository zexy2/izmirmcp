from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.geo import normalize_name
from app.core.validation import InputValidationError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PATH = DATA_DIR / "places.json"
NEIGHBORHOODS_PATH = DATA_DIR / "neighborhoods.json"


@dataclass(frozen=True)
class Place:
    name: str
    kind: str
    lat: float
    lon: float
    district: str | None = None


@dataclass(frozen=True)
class _Index:
    """One lookup table plus the ambiguity map for repeated names."""

    by_key: dict[str, Place]
    duplicates: dict[str, list[Place]] = field(default_factory=dict)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PlaceResolver:
    """Resolve district, neighborhood and landmark labels to reference points.

    Two sources back this resolver:

    * ``places.json`` — a small curated set of districts and landmarks, kept for
      names the municipality does not publish as mahalle (``Kemeraltı``).
    * ``neighborhoods.json`` — the full published muhtarlık inventory
      (1.219 mahalle across 30 districts, retrieved 2026-10-28). This is a
      reference point per mahalle, not a boundary polygon.
    """

    def __init__(
        self,
        path: Path | None = None,
        neighborhoods_path: Path | None = None,
    ):
        document = _load(path or DATA_PATH)
        self.source = document.get("source")
        self.license = document.get("license")
        self.precision = document.get("precision")

        curated: dict[str, Place] = {}
        for item in document.get("places", []):
            place = Place(
                name=item["name"],
                kind=item["kind"],
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                district=item.get("district"),
            )
            curated[normalize_name(place.name)] = place

        neighborhood_doc = _load(neighborhoods_path or NEIGHBORHOODS_PATH)
        self.neighborhood_source = neighborhood_doc.get("source")
        self.neighborhood_license = neighborhood_doc.get("license")
        self.neighborhood_precision = neighborhood_doc.get("precision")

        by_key: dict[str, list[Place]] = {}
        for item in neighborhood_doc.get("places", []):
            place = Place(
                name=item["name"],
                kind="neighborhood",
                lat=float(item["lat"]),
                lon=float(item["lon"]),
                district=item["district"],
            )
            by_key.setdefault(normalize_name(place.name), []).append(place)

        # Curated entries win on exact name collisions (they are the ones the
        # project has always advertised); everything else comes from the census.
        for key, place in curated.items():
            by_key.setdefault(key, []).append(place)

        self._by_key: dict[str, list[Place]] = {
            key: sorted(values, key=lambda place: (place.kind != "district", place.district or ""))
            for key, values in by_key.items()
        }
        self._duplicates = {key: values for key, values in self._by_key.items() if len(values) > 1}

    # -- lookups ---------------------------------------------------------

    def _districts(self) -> list[Place]:
        return [
            values[0]
            for values in self._by_key.values()
            if any(place.kind == "district" for place in values)
        ]

    def _single(self, key: str, value: str) -> Place | None:
        for suffix in (", izmir", " izmir"):
            if key.endswith(suffix):
                key = key[: -len(suffix)].strip()
                break
        values = self._by_key.get(key)
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        # A district label always wins over a mahalle that happens to share it
        # (İzmir has a "Konak" mahalle inside Konak district and a "Karşiyaka"
        # mahalle inside Torbalı). Only genuinely ambiguous mahalle names ask
        # the caller for a district hint.
        districts = [place for place in values if place.kind == "district"]
        if len(districts) == 1:
            return districts[0]
        published = [place for place in values if place.district is not None]
        if len(published) == 1:
            return published[0]
        raise self._ambiguous(value, values)

    def _ambiguous(self, value: str, values: list[Place]) -> InputValidationError:
        options = ", ".join(
            f"{place.name} ({place.district})" if place.district else place.name
            for place in values[:6]
        )
        return InputValidationError(
            f"'{value}' birden fazla yeri gösteriyor: {options}. "
            "Bir ilçe belirtin (district parametresi) veya koordinat verin.",
            field="place",
        )

    # -- public API ------------------------------------------------------

    def candidates(self, value: str) -> list[Place]:
        return list(self._by_key.get(normalize_name(value), []))

    def neighborhoods(self, district: str | None = None) -> list[Place]:
        wanted = normalize_name(district) if district else None
        return sorted(
            (
                place
                for values in self._by_key.values()
                for place in values
                if place.kind == "neighborhood"
                and (wanted is None or normalize_name(place.district or "") == wanted)
            ),
            key=lambda place: (place.district or "", place.name),
        )

    def districts(self) -> list[str]:
        return sorted(place.name for place in self._districts())

    def resolve(self, value: str, *, district: str | None = None) -> Place:
        key = normalize_name(value)
        if district is not None:
            wanted = normalize_name(district)
            matches = [
                place
                for place in self._by_key.get(key, [])
                if normalize_name(place.district or "") == wanted
            ]
            if not matches:
                raise InputValidationError(
                    f"'{value}' için '{district}' ilçesinde yayımlanmış mahalle bulunamadı.",
                    field="place",
                )
            return matches[0]
        place = self._single(key, value)
        if place is not None:
            return place
        examples = ", ".join(sorted(self.districts())[:8])
        raise InputValidationError(
            f"Unknown place '{value}'. Use coordinates or one of the supported "
            f"district/neighborhood names (for example: {examples}).",
            field="place",
        )

    def resolve_neighborhood(self, value: str, *, district: str | None = None) -> Place:
        place = self.resolve(value, district=district)
        if place.kind not in {"neighborhood", "landmark"}:
            raise InputValidationError(
                f"'{value}' bir mahalle adı değil (tür: {place.kind}).",
                field="place",
            )
        return place

    def resolve_district(self, value: str) -> Place:
        """Resolve an İzmir district name, rejecting neighborhoods."""
        key = normalize_name(value)
        for suffix in (", izmir", " izmir"):
            if key.endswith(suffix):
                key = key[: -len(suffix)].strip()
                break
        matches = [place for place in self._by_key.get(key, []) if place.kind == "district"]
        if not matches:
            examples = ", ".join(sorted(self.districts())[:8])
            raise InputValidationError(
                f"Unknown İzmir district '{value}'. Use one of the published district "
                f"names (for example: {examples}).",
                field="district",
            )
        return matches[0]

    def names(self) -> list[str]:
        return sorted({place.name for values in self._by_key.values() for place in values})
