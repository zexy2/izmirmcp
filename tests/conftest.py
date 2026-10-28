from __future__ import annotations

from app.core.source_cache import CacheInfo


def fresh(source_updated_at: str | None = None) -> CacheInfo:
    return CacheInfo(
        status="fresh",
        retrieved_at="2026-10-28T00:00:00+00:00",
        source_updated_at=source_updated_at,
        age_seconds=0.0,
    )
