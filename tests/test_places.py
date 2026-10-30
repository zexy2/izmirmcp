from __future__ import annotations

import pytest

from app.core.validation import InputValidationError
from app.services.places import PlaceResolver


def test_resolves_district_and_neighborhood():
    resolver = PlaceResolver()
    konak = resolver.resolve("Konak")
    assert konak.kind == "district"
    assert abs(konak.lat - 38.41872) < 0.001
    alsancak = resolver.resolve("alsancak")
    assert alsancak.kind == "neighborhood"
    # Reference point is the published muhtarlık position, not a landmark centre.
    assert abs(alsancak.lon - 27.1427) < 0.002


def test_turkish_case_and_suffix_are_tolerated():
    resolver = PlaceResolver()
    assert resolver.resolve("KARŞIYAKA").name == "Karşıyaka"
    assert resolver.resolve("Konak, İzmir").name == "Konak"


def test_unknown_place_is_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        PlaceResolver().resolve("Atlantis")
    assert excinfo.value.field == "place"
    assert "Bilinmeyen yer" in str(excinfo.value)


def test_neighborhood_index_covers_published_muhtarlik_inventory():
    resolver = PlaceResolver()
    neighborhoods = resolver.neighborhoods()
    districts = resolver.districts()
    assert len(districts) == 30
    assert len(neighborhoods) >= 1200
    # Curated landmarks carry no district on purpose; every published mahalle does.
    published_districts = {place.district for place in neighborhoods if place.district}
    assert published_districts == set(districts)


def test_neighborhood_resolves_with_its_district():
    resolver = PlaceResolver()
    place = resolver.resolve_neighborhood("Abdi İpekçi")
    assert place.kind == "neighborhood"
    assert place.district == "Karabağlar"
    assert 38.3 < place.lat < 38.45
    assert 27.0 < place.lon < 27.2


def test_ambiguous_neighborhood_requires_a_district():
    resolver = PlaceResolver()
    # Mahalle names repeat heavily across İzmir districts (17 × "Atatürk").
    candidates = resolver.candidates("Atatürk")
    assert len(candidates) > 1
    with pytest.raises(InputValidationError) as excinfo:
        resolver.resolve("Atatürk")
    assert excinfo.value.field == "place"
    assert "district" in str(excinfo.value).lower()


def test_ambiguous_neighborhood_is_resolved_with_a_district_hint():
    resolver = PlaceResolver()
    options = resolver.candidates("Atatürk")
    target = next(place for place in options if place.district)
    place = resolver.resolve("Atatürk", district=target.district)
    assert place.district == target.district
    assert place.name == "Atatürk"


def test_neighborhood_listing_can_be_filtered_by_district():
    resolver = PlaceResolver()
    in_konak = resolver.neighborhoods(district="Konak")
    assert in_konak
    assert all(place.district == "Konak" for place in in_konak)
    assert len(in_konak) < len(resolver.neighborhoods())


def test_unpublished_neighborhood_is_rejected_not_guessed():
    resolver = PlaceResolver()
    with pytest.raises(InputValidationError):
        resolver.resolve_neighborhood("Olmayan Mahalle Adı")


def test_curated_landmarks_still_resolve_when_not_a_muhtarlik():
    resolver = PlaceResolver()
    # Landmark entries are not official mahalle names; they must keep working.
    place = resolver.resolve("Kemeraltı")
    assert place.kind in {"neighborhood", "landmark"}
