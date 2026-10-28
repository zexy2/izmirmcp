"""SQLite-backed spatial index for the nearby layers.

The previous implementation downloaded every layer into memory on each call and
filtered with haversine. This store replaces that: rows are written once, and a
rectangle (RTree) or radius query reads only the candidate range from the index.
Distances are still computed in Python so the reported metres stay identical to
the in-memory path.

Failure policy matches the rest of the project: a broken database raises
``GeoStoreError`` (a source-side failure), never a silent empty result.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.core.geo import EARTH_RADIUS_M, haversine_m
from app.storage.db import connect, init_database

# One degree of latitude is ~111.32 km; longitude shrinks with cos(lat).
_M_PER_DEG_LAT = 111_320.0


class GeoStoreError(RuntimeError):
    """The local spatial store is missing, corrupt or unusable."""


def _bbox_for_radius(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Return ``(min_lon, max_lon, min_lat, max_lat)`` covering the circle.

    Deliberately conservative: the box always contains the circle, so the RTree
    candidate set can never miss a point that the exact distance test would keep.
    """
    d_lat = math.degrees(radius_m / _M_PER_DEG_LAT)
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    d_lon = math.degrees(radius_m / (_M_PER_DEG_LAT * cos_lat))
    return lon - d_lon, lon + d_lon, lat - d_lat, lat + d_lat


def _valid_point(lat: Any, lon: Any) -> bool:
    if isinstance(lat, bool) or isinstance(lon, bool):
        return False
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _public(row: sqlite3.Row) -> dict[str, Any]:
    """Present ``external_id`` as ``id`` and expose the stored payload."""
    payload = json.loads(row["payload"])
    return {
        "kind": row["kind"],
        "id": row["external_id"],
        "name": row["name"],
        "lat": row["lat"],
        "lon": row["lon"],
        "payload": payload,
        **payload,
    }


class GeoStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # -- setup -----------------------------------------------------------

    def _connection(self) -> sqlite3.Connection:
        try:
            connection = connect(self.path)
            init_database(connection)
            return connection
        except sqlite3.Error as exc:
            raise GeoStoreError("spatial store could not be opened") from exc

    def replace_all(self, points: Iterable[dict[str, Any]]) -> int:
        """Atomically replace every indexed point; returns the row count.

        An empty input is rejected on purpose: wiping the index because a source
        returned nothing would turn an outage into a silently empty map.
        """
        rows: list[tuple[str, str, str | None, float, float, str]] = []
        for item in points:
            lat, lon = item.get("lat"), item.get("lon")
            kind = str(item.get("kind") or "").strip()
            external_id = str(item.get("id") or "").strip()
            if not kind or not external_id:
                raise GeoStoreError("every point needs a kind and an id")
            if not _valid_point(lat, lon):
                # Rows without usable coordinates cannot be indexed; skipping is
                # honest because they are never returned by a spatial query.
                continue
            payload = {
                key: value
                for key, value in item.items()
                if key not in {"kind", "id", "lat", "lon"}
            }
            rows.append((kind, external_id, item.get("name"), float(lat), float(lon),
                         json.dumps(payload, ensure_ascii=False)))
        if not rows:
            raise GeoStoreError("refusing to replace the spatial index with no usable points")

        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM geo_points_rtree")
                connection.execute("DELETE FROM geo_points")
                connection.executemany(
                    "INSERT INTO geo_points (kind, external_id, name, lat, lon, payload)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                connection.execute(
                    "INSERT INTO geo_points_rtree (rowid, min_lon, max_lon, min_lat, max_lat)"
                    " SELECT rowid, lon, lon, lat, lat FROM geo_points"
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                raise GeoStoreError("spatial index could not be rebuilt") from exc
        return len(rows)

    def replace_kind(self, kind: str, points: Iterable[dict[str, Any]]) -> int:
        """Atomically replace all points of one kind; other kinds are untouched."""
        rows: list[tuple[str, str, str | None, float, float, str]] = []
        for item in points:
            lat, lon = item.get("lat"), item.get("lon")
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                raise GeoStoreError("every point needs an id")
            if not _valid_point(lat, lon):
                continue
            payload = {
                key: value
                for key, value in item.items()
                if key not in {"kind", "id", "lat", "lon"}
            }
            rows.append((kind, external_id, item.get("name"), float(lat), float(lon),
                         json.dumps(payload, ensure_ascii=False)))
        if not rows:
            raise GeoStoreError(f"refusing to index zero usable {kind} points")

        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                ids = [
                    row[0] for row in connection.execute(
                        "SELECT rowid FROM geo_points WHERE kind = ?", (kind,)
                    )
                ]
                if ids:
                    connection.executemany(
                        "DELETE FROM geo_points_rtree WHERE rowid = ?", [(i,) for i in ids]
                    )
                connection.execute("DELETE FROM geo_points WHERE kind = ?", (kind,))
                connection.executemany(
                    "INSERT INTO geo_points (kind, external_id, name, lat, lon, payload)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                connection.execute(
                    "INSERT INTO geo_points_rtree (rowid, min_lon, max_lon, min_lat, max_lat)"
                    " SELECT rowid, lon, lon, lat, lat FROM geo_points WHERE kind = ?",
                    (kind,),
                )
                connection.commit()
            except sqlite3.Error as exc:
                connection.rollback()
                raise GeoStoreError(f"spatial index for {kind} could not be rebuilt") from exc
        return len(rows)

    # -- metadata --------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            connection.commit()

    def meta(self) -> dict[str, str]:
        try:
            with self._connection() as connection:
                return {
                    str(row["key"]): str(row["value"])
                    for row in connection.execute("SELECT key, value FROM app_meta")
                }
        except sqlite3.Error as exc:
            raise GeoStoreError("spatial store metadata is unreadable") from exc

    def counts(self) -> dict[str, int]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT kind, COUNT(*) AS n FROM geo_points GROUP BY kind"
                ).fetchall()
        except sqlite3.Error as exc:
            raise GeoStoreError("spatial store is unreadable") from exc
        return {str(row["kind"]): int(row["n"]) for row in rows}

    # -- queries ---------------------------------------------------------

    def _select(self, clause: str, params: tuple, *, limit: int | None) -> list[dict[str, Any]]:
        sql = (
            "SELECT g.rowid, g.kind, g.external_id, g.name, g.lat, g.lon, g.payload"
            " FROM geo_points g JOIN geo_points_rtree r ON r.rowid = g.rowid"
            f" WHERE {clause}"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        try:
            with self._connection() as connection:
                return [_public(row) for row in connection.execute(sql, params)]
        except sqlite3.Error as exc:
            raise GeoStoreError("spatial query failed") from exc

    def radius(
        self,
        lat: float,
        lon: float,
        *,
        radius_m: float,
        kinds: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return points within ``radius_m`` metres, nearest first."""
        min_lon, max_lon, min_lat, max_lat = _bbox_for_radius(lat, lon, radius_m)
        clause = "r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?"
        params: tuple = (min_lon, max_lon, min_lat, max_lat)
        if kinds:
            clause += f" AND g.kind IN ({','.join('?' * len(kinds))})"
            params += tuple(kinds)
        rows = self._select(clause, params, limit=None)
        kept = []
        for row in rows:
            distance = haversine_m(lat, lon, row["lat"], row["lon"])
            if distance <= radius_m:
                kept.append({**row, "distance_m": distance})
        kept.sort(key=lambda row: (row["distance_m"], row.get("name") or ""))
        return kept[:limit] if limit else kept

    def bbox(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        kinds: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return points inside a rectangle; every edge is inclusive."""
        clause = "r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?"
        params: tuple = (min_lon, max_lon, min_lat, max_lat)
        if kinds:
            clause += f" AND g.kind IN ({','.join('?' * len(kinds))})"
            params += tuple(kinds)
        rows = self._select(clause, params, limit=limit)
        return [row for row in rows
                if min_lat <= row["lat"] <= max_lat and min_lon <= row["lon"] <= max_lon]

    def distance_degrees_hint(self) -> float:
        """Expose the earth constant used for distances, for diagnostics."""
        return EARTH_RADIUS_M
