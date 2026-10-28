from __future__ import annotations

import pytest

from app.core.source_cache import CacheInfo, clear_cache


def fresh(source_updated_at: str | None = None) -> CacheInfo:
    return CacheInfo(
        status="fresh",
        retrieved_at="2026-10-28T00:00:00+00:00",
        source_updated_at=source_updated_at,
        age_seconds=0.0,
    )


@pytest.fixture(autouse=True)
def _isolate_source_cache():
    """The source cache is process-global; isolate every test from its keys.

    Without this, one test's cached DataStore page can satisfy the next test's
    differently-stubbed client and make failures order-dependent.
    """
    clear_cache()
    yield
    clear_cache()
