"""The local SQL guard is deny-by-default.

A custom SQL endpoint is only safe if the parser and the SQLite authorizer both
refuse everything outside one bounded SELECT over ``records``. These tests try
the obvious escapes directly against the guard, without a service or network.
"""

from __future__ import annotations

import pytest

from app.core.validation import InputValidationError
from app.storage.guarded_sql import (
    QueryRejected,
    execute_snapshot_query,
    validate_fields,
    validate_sql,
)

FIELDS = (
    ("_id", "int"),
    ("ILCE", "text"),
    ("N", "int"),
)
ROWS = [
    {"_id": 1, "ILCE": "Konak", "N": 10},
    {"_id": 2, "ILCE": "Konak", "N": 20},
]


def run(sql: str, *, limit: int = 10):
    return execute_snapshot_query(FIELDS, ROWS, sql, limit=limit, timeout_seconds=1.0)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM records",
        "UPDATE records SET N = 0",
        "SELECT * FROM records; DELETE FROM records",
        "SELECT * FROM records UNION SELECT * FROM records",
        "SELECT * FROM records AS a JOIN records AS b ON a._id = b._id",
        "SELECT (SELECT COUNT(*) FROM records) AS n FROM records",
        "WITH x AS (SELECT * FROM records) SELECT * FROM x",
        "SELECT * FROM sqlite_master",
        "PRAGMA table_info(records)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "SELECT load_extension('x') AS n FROM records",
        "SELECT readfile('/etc/passwd') AS n FROM records",
    ],
)
def test_guard_rejects_everything_outside_the_subset(sql):
    with pytest.raises((InputValidationError, QueryRejected)):
        run(sql)


def test_guard_allows_aggregates_and_aliases():
    data, truncated = run(
        "SELECT ILCE, COUNT(*) AS n, SUM(N) AS total FROM records GROUP BY ILCE",
        limit=5,
    )
    assert truncated is False
    assert data == [{"ILCE": "Konak", "n": 2, "total": 30}]


def test_guard_enforces_the_outer_limit():
    data, truncated = run("SELECT * FROM records ORDER BY N DESC", limit=1)
    assert data == [{"_id": 2, "ILCE": "Konak", "N": 20}]
    assert truncated is True


def test_guard_refuses_a_snapshot_without_a_stable_id():
    with pytest.raises(ValueError):
        validate_fields([{"id": "ILCE", "type": "text"}])


def test_guard_refuses_case_colliding_columns():
    with pytest.raises(ValueError):
        validate_fields([{"id": "_id", "type": "int"}, {"id": "ilce", "type": "text"}, {"id": "ILCE", "type": "text"}])


def test_validate_sql_returns_canonical_sql():
    assert validate_sql("select count(*) as n from records").lower().startswith("select")


def test_guard_caps_snapshot_rows():
    from app.storage.guarded_sql import SnapshotRejected

    with pytest.raises(SnapshotRejected):
        execute_snapshot_query(FIELDS, ROWS, "SELECT ILCE FROM records", limit=10, timeout_seconds=1.0, max_rows=1)


def test_guard_caps_snapshot_bytes():
    from app.storage.guarded_sql import SnapshotRejected

    rows = [{"_id": i, "ILCE": "x" * 1000, "N": i} for i in range(1, 6)]
    with pytest.raises(SnapshotRejected):
        execute_snapshot_query(FIELDS, rows, "SELECT ILCE FROM records", limit=10, timeout_seconds=1.0, max_bytes=2048)
    data, _ = execute_snapshot_query(
        FIELDS, rows, "SELECT COUNT(*) AS c FROM records", limit=10, timeout_seconds=1.0, max_bytes=10_000
    )
    assert data == [{"c": 5}]


def test_guard_caller_cannot_raise_caps_above_hard_limit():
    import app.storage.guarded_sql as guarded

    rows = [{"_id": i, "ILCE": "a", "N": i} for i in range(1, 4)]
    original = guarded.MAX_SNAPSHOT_ROWS
    guarded.MAX_SNAPSHOT_ROWS = 2
    try:
        with pytest.raises(guarded.SnapshotRejected):
            execute_snapshot_query(
                FIELDS, rows, "SELECT ILCE FROM records", limit=10, timeout_seconds=1.0, max_rows=10**9
            )
    finally:
        guarded.MAX_SNAPSHOT_ROWS = original


def test_authorizer_allows_empty_column_read_without_database(monkeypatch):
    """Pin the branch for SQLITE_READ with database None and an empty column."""
    import sqlite3

    import app.storage.guarded_sql as guarded

    captured = {}
    real_connect = sqlite3.connect

    class Proxy:
        def __init__(self, conn):
            self._conn = conn

        def set_authorizer(self, fn):
            captured["fn"] = fn
            return self._conn.set_authorizer(fn)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(guarded.sqlite3, "connect", lambda *a, **k: Proxy(real_connect(*a, **k)))
    data, _ = run("SELECT COUNT(*) AS c FROM records")
    assert data == [{"c": 2}]
    authorize = captured["fn"]
    read = sqlite3.SQLITE_READ
    assert authorize(read, "records", "", None, None) == sqlite3.SQLITE_OK
    assert authorize(read, "records", "", "main", None) == sqlite3.SQLITE_OK
    assert authorize(read, "records", "ILCE", None, None) == sqlite3.SQLITE_DENY
    assert authorize(read, "records", "", "temp", None) == sqlite3.SQLITE_DENY
    assert authorize(read, "sqlite_master", "", None, None) == sqlite3.SQLITE_DENY
