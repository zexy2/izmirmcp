"""Shared SQLite bootstrap: WAL, schema version and the spatial index."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

# SQLite ships RTree as a loadable extension compiled into most distributions.
# If a build lacks it the server must fail loudly at startup instead of silently
# falling back to a full table scan on every proximity query.
SCHEMA = """
CREATE TABLE IF NOT EXISTS geo_points (
    rowid INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (kind, external_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS geo_points_rtree USING rtree(
    rowid, min_lon, max_lon, min_lat, max_lat
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS geo_points_kind ON geo_points(kind);
"""


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open the shared database with WAL and a bounded lock wait."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_database(connection: sqlite3.Connection) -> None:
    """Create the schema and stamp the version; idempotent."""
    connection.executescript(SCHEMA)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.commit()
