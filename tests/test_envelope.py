from __future__ import annotations

from app.core.envelope import (
    Source,
    error_envelope,
    public_page_url,
    success_envelope,
)


def test_success_envelope_has_canonical_fields():
    envelope = success_envelope(
        summary="1 result",
        data=[{"name": "Konak"}],
        sources=[Source(name="Test")],
    )
    assert envelope["ok"] is True
    assert envelope["summary"] == "1 result"
    assert envelope["data"] == [{"name": "Konak"}]
    assert envelope["freshness"]["status"] == "unknown"
    assert envelope["result_info"]["returned"] == 1
    assert set(envelope) >= {
        "ok", "summary", "data", "freshness", "sources",
        "limits", "warnings", "next_queries", "error", "result_info",
    }


def test_error_envelope_marks_temporary_source_errors():
    envelope = error_envelope(
        summary="unavailable",
        warning="API returned HTTP 500",
        code="source_unavailable",
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["error"]["temporary"] is True
    assert envelope["freshness"]["status"] == "broken"


def test_public_page_url_hides_api_and_file_endpoints():
    assert public_page_url("https://www.izmir.bel.tr/tr/NobetciEczane/27") == (
        "https://www.izmir.bel.tr/tr/NobetciEczane/27"
    )
    assert public_page_url("https://openapi.izmir.bel.tr/api/ibb/nobetcieczaneler") is None
    assert public_page_url("https://openfiles.izmir.bel.tr/309436/docs/x.csv") is None
    assert public_page_url("http://acikveri.bizizmir.com") is None


def test_source_serialization_strips_endpoint_urls():
    payload = success_envelope(
        summary="x",
        data=[],
        sources=[Source(name="API", url="https://openapi.izmir.bel.tr/api/x")],
    )
    assert payload["sources"][0]["url"] is None
