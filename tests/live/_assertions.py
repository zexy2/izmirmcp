"""Strict assertions for live checks: an error envelope is a failure, never a pass."""

from __future__ import annotations


def assert_ok(envelope, *, keys=(), allow_empty=False):
    """Assert a success envelope with list data whose rows carry ``keys``.

    ``allow_empty`` is the only way to accept zero rows and must be passed explicitly.
    """
    assert envelope["ok"] is True, envelope.get("error")
    assert envelope["error"] is None
    data = envelope["data"]
    assert isinstance(data, list)
    assert envelope["sources"]
    if not allow_empty:
        assert data, f"empty data: {envelope.get('summary')}"
    for row in data:
        missing = [key for key in keys if key not in row]
        assert not missing, f"missing keys {missing} in {row}"
    return data
