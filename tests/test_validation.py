from __future__ import annotations

import pytest

from app.core.validation import (
    InputValidationError,
    resolve_limit,
    validate_date,
    validate_filters,
    validate_lat_lon,
    validate_radius,
)


def test_limit_defaults_and_bounds():
    assert resolve_limit(None, 10, 50) == 10
    assert resolve_limit(5, 10, 50) == 5
    with pytest.raises(InputValidationError):
        resolve_limit(0, 10, 50)
    with pytest.raises(InputValidationError):
        resolve_limit(51, 10, 50)


def test_coordinate_and_radius_bounds():
    assert validate_lat_lon(38.42, 27.13) == (38.42, 27.13)
    with pytest.raises(InputValidationError):
        validate_lat_lon(91, 27.13)
    assert validate_radius(1500, 5000) == 1500
    with pytest.raises(InputValidationError):
        validate_radius(6000, 5000)


def test_date_validation_defaults_to_today():
    assert validate_date(None) == validate_date("")
    assert validate_date("2026-10-28") == "2026-10-28"
    with pytest.raises(InputValidationError):
        validate_date("28.10.2026")


def test_filters_reject_nested_values():
    assert validate_filters({"ILCE": "Konak"}) == {"ILCE": "Konak"}
    with pytest.raises(InputValidationError):
        validate_filters({"ILCE": {"nested": True}})
    with pytest.raises(InputValidationError):
        validate_filters({f"k{i}": i for i in range(11)})
