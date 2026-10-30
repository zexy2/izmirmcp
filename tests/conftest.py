from __future__ import annotations

import pytest

from app.core.settings import get_settings
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


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch):
    """Point every service at a scratch SQLite file.

    The spatial index and quota store are on-disk by design. The isolation works
    through the environment variable (the same path a real deployment uses) so
    it does not have to replace ``get_settings`` or its cache, which other tests
    manipulate directly.
    """
    path = str(tmp_path / "isolated.sqlite3")
    monkeypatch.setenv("IZMIR_MCP_DATABASE_PATH", path)
    monkeypatch.setenv(
        "IZMIR_MCP_GTFS_DATABASE_PATH", str(tmp_path / "isolated-gtfs.sqlite3")
    )
    import app.core.settings as settings_module

    settings_module.get_settings.cache_clear()
    yield path
    settings_module.get_settings.cache_clear()
