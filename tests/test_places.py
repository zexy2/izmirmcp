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
    assert abs(alsancak.lon - 27.14812) < 0.001


def test_turkish_case_and_suffix_are_tolerated():
    resolver = PlaceResolver()
    assert resolver.resolve("KARŞIYAKA").name == "Karşıyaka"
    assert resolver.resolve("Konak, İzmir").name == "Konak"


def test_unknown_place_is_rejected():
    with pytest.raises(InputValidationError) as excinfo:
        PlaceResolver().resolve("Atlantis")
    assert excinfo.value.field == "place"
    assert "Unknown place" in str(excinfo.value)
