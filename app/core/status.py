"""Readiness and status reporting.

Readiness here means "the server can serve the tools it advertises", not "the
outside world is reachable". Probing third-party city APIs on every readiness
probe would hammer them and turn their outage into a restart loop. The one
genuinely local dependency that can silently break a whole tool family is the
GTFS timetable store, so it is checked explicitly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.settings import Settings


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class Readiness:
    ready: bool
    checks: dict[str, Check] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": {name: check.as_dict() for name, check in self.checks.items()},
        }


def check_timetable_store(settings: Settings) -> Check:
    """The GTFS store is local state; a corrupt one breaks three tools.

    A *missing* store is not a failure: it is built lazily on first use. A
    present-but-corrupt store is, because lazy rebuild will not help.
    """
    path = Path(settings.gtfs_database_path)
    if not path.exists():
        return Check(
            "timetable_store",
            "absent",
            "not built yet; izmir_bus_departures builds it on first use",
        )
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            has_meta = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='gtfs_meta'"
            ).fetchone()
        if not has_meta:
            return Check("timetable_store", "absent", "no timetable tables yet")
        return Check("timetable_store", "ok")
    except sqlite3.Error as exc:
        return Check("timetable_store", "broken", type(exc).__name__)


def check_database_writable(settings: Settings) -> Check:
    """Quota, spatial-index and GTFS writes need writable parent directories."""
    for raw_path in (settings.database_path, settings.gtfs_database_path):
        parent = Path(raw_path).parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return Check("database_directory", "broken", type(exc).__name__)
        if not parent.is_dir():
            return Check("database_directory", "broken", "not a directory")
    return Check("database_directory", "ok")


def check_tool_surface(tool_count: int) -> Check:
    if tool_count <= 0:
        return Check("tool_surface", "empty", "no tools registered")
    return Check("tool_surface", "ok", f"{tool_count} tools")


def evaluate(settings: Settings, tool_count: int) -> Readiness:
    """Readiness requires a non-empty surface and a usable local datastore.

    ``timetable_store=absent`` and ``broken`` differ deliberately: absent is
    normal on a fresh install, broken means the file cannot be opened.
    """
    checks = {
        "tool_surface": check_tool_surface(tool_count),
        "timetable_store": check_timetable_store(settings),
        "database_directory": check_database_writable(settings),
    }
    ready = (
        checks["tool_surface"].status == "ok"
        and checks["timetable_store"].status in {"ok", "absent"}
        and checks["database_directory"].status == "ok"
    )
    return Readiness(ready=ready, checks=checks)


def source_cache_status() -> dict[str, Any]:
    """Upstream cache health for /status; keys are hashed, never raw."""
    from app.core.source_cache import snapshot

    return snapshot()


def public_readiness(readiness: Readiness) -> dict[str, Any]:
    """Readiness payload for an unauthenticated probe (no paths, no internals)."""
    return {
        "ready": readiness.ready,
        "upstream_health": "not_checked",
        "checks": {name: check.status for name, check in readiness.checks.items()},
    }
