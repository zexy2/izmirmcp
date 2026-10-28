from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.core.status import (
    check_timetable_store,
    evaluate,
    public_readiness,
)


def _settings(tmp_path: Path, **overrides):
    import dataclasses

    base = get_settings()
    return dataclasses.replace(
        base, database_path=str(tmp_path / "db.sqlite3"), **overrides
    )


def test_missing_timetable_store_is_absent_not_broken(tmp_path: Path):
    check = check_timetable_store(_settings(tmp_path))
    assert check.status == "absent"
    assert "builds it on first use" in (check.detail or "")


def test_corrupt_timetable_store_is_broken(tmp_path: Path):
    path = tmp_path / "db.sqlite3"
    path.write_bytes(b"this is not a database")
    check = check_timetable_store(_settings(tmp_path))
    assert check.status == "broken"


def test_built_store_is_ok(tmp_path: Path):
    path = tmp_path / "db.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE gtfs_meta (key TEXT PRIMARY KEY, value TEXT)")
    assert check_timetable_store(_settings(tmp_path)).status == "ok"


def test_evaluate_is_ready_without_a_timetable_store(tmp_path: Path):
    readiness = evaluate(_settings(tmp_path), tool_count=19)
    assert readiness.ready is True
    assert readiness.checks["timetable_store"].status == "absent"


def test_evaluate_is_not_ready_with_an_empty_surface(tmp_path: Path):
    readiness = evaluate(_settings(tmp_path), tool_count=0)
    assert readiness.ready is False
    assert readiness.checks["tool_surface"].status == "empty"


def test_evaluate_is_not_ready_with_a_broken_store(tmp_path: Path):
    (tmp_path / "db.sqlite3").write_bytes(b"garbage")
    readiness = evaluate(_settings(tmp_path), tool_count=19)
    assert readiness.ready is False
    assert readiness.checks["timetable_store"].status == "broken"


def test_public_readiness_hides_paths_and_details(tmp_path: Path):
    readiness = evaluate(_settings(tmp_path), tool_count=19)
    payload = public_readiness(readiness)
    assert payload["ready"] is True
    assert payload["upstream_health"] == "not_checked"
    assert all(isinstance(value, str) for value in payload["checks"].values())
    assert str(tmp_path) not in str(payload)


def test_unwritable_database_directory_is_detected(tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    import dataclasses

    settings = dataclasses.replace(
        get_settings(), database_path=str(blocker / "db.sqlite3")
    )
    readiness = evaluate(settings, tool_count=19)
    assert readiness.ready is False
    assert readiness.checks["database_directory"].status == "broken"
