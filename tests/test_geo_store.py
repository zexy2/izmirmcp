from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.storage.geo import GeoStore, GeoStoreError
from app.storage.db import SCHEMA_VERSION, connect, init_database

POINTS = [
    {"kind": "parking", "id": "p1", "name": "Konak Otopark", "lat": 38.4190, "lon": 27.1290},
    {"kind": "parking", "id": "p2", "name": "Uzak Otopark", "lat": 38.5000, "lon": 27.2000},
    {"kind": "pharmacy", "id": "f1", "name": "Eczane", "lat": 38.4189, "lon": 27.1285},
    {"kind": "bus_stop", "id": "b1", "name": "Durak", "lat": 38.4100, "lon": 27.1200},
]


def _store(tmp_path: Path) -> GeoStore:
    return GeoStore(tmp_path / "geo.sqlite3")


def test_schema_version_is_declared(tmp_path: Path):
    assert SCHEMA_VERSION >= 1
    with connect(tmp_path / "db.sqlite3") as conn:
        init_database(conn)
        row = conn.execute("PRAGMA user_version").fetchone()
    assert row[0] == SCHEMA_VERSION


def test_wal_mode_is_enabled(tmp_path: Path):
    with connect(tmp_path / "db.sqlite3") as conn:
        init_database(conn)
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(journal).lower() == "wal"


def test_rtree_is_available_in_this_python(tmp_path: Path):
    """İzmir queries depend on SQLite RTree; fail loudly if it is missing."""
    with connect(tmp_path / "db.sqlite3") as conn:
        init_database(conn)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "geo_points_rtree" in names


def test_replace_and_radius_query_returns_nearest_first(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    rows = store.radius(38.41872, 27.12827, radius_m=300, kinds=["parking", "pharmacy"])
    assert [row["id"] for row in rows][0] == "f1"
    assert {row["id"] for row in rows} == {"f1", "p1"}
    distances = [row["distance_m"] for row in rows]
    assert distances == sorted(distances)


def test_radius_respects_kind_filter(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    rows = store.radius(38.41872, 27.12827, radius_m=5000, kinds=["bus_stop"])
    assert [row["id"] for row in rows] == ["b1"]


def test_bbox_query_includes_edges(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    rows = store.bbox(min_lon=27.1200, min_lat=38.4100, max_lon=27.1300, max_lat=38.4200)
    ids = {row["id"] for row in rows}
    assert ids == {"p1", "f1", "b1"}


def test_bbox_excludes_outside_points(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    rows = store.bbox(min_lon=27.1200, min_lat=38.4100, max_lon=27.1300, max_lat=38.4200)
    assert "p2" not in {row["id"] for row in rows}


def test_count_reports_per_kind(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    counts = store.counts()
    assert counts == {"parking": 2, "pharmacy": 1, "bus_stop": 1}


def test_replace_all_is_atomic_and_drops_stale_rows(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    store.replace_all([POINTS[0]])
    assert store.counts() == {"parking": 1}


def test_empty_replace_is_rejected_not_silently_wiped(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all(POINTS)
    with pytest.raises(GeoStoreError):
        store.replace_all([])
    assert store.counts() == {"parking": 2, "pharmacy": 1, "bus_stop": 1}


def test_rows_without_coordinates_are_skipped(tmp_path: Path):
    store = _store(tmp_path)
    store.replace_all([*POINTS, {"kind": "parking", "id": "bad", "name": "x", "lat": None, "lon": None}])
    assert store.counts() == {"parking": 2, "pharmacy": 1, "bus_stop": 1}


def test_out_of_bounds_coordinates_are_rejected(tmp_path: Path):
    store = _store(tmp_path)
    with pytest.raises(GeoStoreError):
        store.replace_all([{"kind": "parking", "id": "x", "name": "x", "lat": 91.0, "lon": 0.0}])


def test_metadata_roundtrip(tmp_path: Path):
    store = _store(tmp_path)
    store.set_meta("built_at", "2026-10-28T00:00:00+00:00")
    assert store.meta().get("built_at") == "2026-10-28T00:00:00+00:00"


def test_payload_survives_the_roundtrip(tmp_path: Path):
    """Rows must keep their source payload so callers can decorate them."""
    store = _store(tmp_path)
    store.replace_all(
        [
            {"kind": "parking", "id": "p1", "name": "Konak", "lat": 38.4190, "lon": 27.1290, "extra": {"free": 3}},
        ]
    )
    rows = store.radius(38.41872, 27.12827, radius_m=500)
    assert rows[0]["payload"]["extra"] == {"free": 3}


def test_corrupt_database_raises_a_domain_error(tmp_path: Path):
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a database")
    with pytest.raises(GeoStoreError):
        GeoStore(path).counts()
