from __future__ import annotations


from app.core.error_responses import validation_error_envelope
from app.core.validation import InputValidationError


def test_validation_error_names_the_field_and_gives_a_repair():
    payload = validation_error_envelope(
        InputValidationError("radius_m must be <= 5000", field="radius_m"),
        tool="izmir_nearby",
    )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["field"] == "radius_m"
    assert payload["error"]["repair"]["constraint"]
    assert payload["error"]["repair"]["tool"] == "izmir_nearby"
    assert payload["error"]["next_step"] == payload["error"]["repair"]["next_step"]


def test_empty_selection_gets_its_own_hint():
    payload = validation_error_envelope(
        InputValidationError("kinds must be a non-empty subset of: wifi", field="kinds"),
        tool="izmir_city_services_nearby",
    )
    assert "En az bir" in payload["error"]["repair"]["next_step"]


def test_unknown_field_still_returns_a_valid_envelope():
    payload = validation_error_envelope(InputValidationError("something odd", field="mystery"))
    assert payload["error"]["repair"] is None
    assert payload["error"]["field"] == "mystery"
    assert payload["error"]["next_step"]


def test_no_field_means_no_repair():
    payload = validation_error_envelope(InputValidationError("bad input", field=""))
    assert payload["error"]["repair"] is None


def test_envelope_shape_is_stable():
    payload = validation_error_envelope(InputValidationError("lat must be between -90 and 90", field="lat"))
    for key in (
        "ok",
        "summary",
        "data",
        "freshness",
        "sources",
        "limits",
        "warnings",
        "next_queries",
        "error",
        "result_info",
    ):
        assert key in payload
    assert payload["error"]["temporary"] is False


def test_source_rate_limited_is_temporary_with_retry_hint():
    from app.connectors.http import SourceRateLimitedError
    from app.core.error_responses import source_error_envelope

    payload = source_error_envelope(SourceRateLimitedError("rate limited"), summary="Kaynak sınırlı.")
    assert payload["error"]["code"] == "source_rate_limited"
    assert payload["error"]["temporary"] is True
