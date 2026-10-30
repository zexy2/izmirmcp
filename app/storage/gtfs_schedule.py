"""Persistent GTFS timetable storage for scheduled EShot departures.

The published archive carries about 2.1 million ``stop_times`` rows. Parsing it
per request is not viable, so the archive is normalised once into a local SQLite
database with indexes on ``(stop_id, departure_sec)``. A build is atomic: the
database is populated in a temporary file and swapped in only after the archive,
the required members, the row budget and the schema all validate.

Only published timetable data is stored. There is no realtime feed, no invented
ETA and no fallback row when a source member is missing.

The store is local state and is kept out of the container image. It is rebuilt
from the published archive at run time, either lazily by ``izmir_bus_departures``
or eagerly with ``python -m app.storage.gtfs_schedule`` (used by the image
entrypoint so the first query does not pay the build cost).
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import httpx

ISTANBUL = ZoneInfo("Europe/Istanbul")
WEEKDAY_COLUMNS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)
REQUIRED_MEMBERS = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt")
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
# www.eshot.gov.tr answers 406 to an open ``Accept`` for the zip; ``*/*`` works.
GTFS_ACCEPT = "*/*"
GTFS_FETCH_TIMEOUT_SECONDS = 120.0
INT_META_KEYS = frozenset(
    {
        "stops_rows", "routes_rows", "trips_rows", "stop_times_rows",
        "calendar_rows", "calendar_dates_rows", "skipped_stop_times", "zip_bytes",
    }
)

SCHEMA = """
CREATE TABLE gtfs_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stops (
    stop_id TEXT PRIMARY KEY,
    stop_name TEXT,
    stop_code TEXT,
    stop_lat REAL,
    stop_lon REAL
);
CREATE TABLE routes (
    route_id TEXT PRIMARY KEY,
    short_name TEXT,
    long_name TEXT,
    route_type TEXT
);
CREATE TABLE trips (
    trip_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    headsign TEXT,
    direction_id TEXT
);
CREATE TABLE stop_times (
    trip_id TEXT NOT NULL,
    stop_id TEXT NOT NULL,
    departure_sec INTEGER NOT NULL,
    stop_sequence INTEGER,
    pickup_type TEXT
);
CREATE TABLE calendar (
    service_id TEXT PRIMARY KEY,
    monday INTEGER NOT NULL,
    tuesday INTEGER NOT NULL,
    wednesday INTEGER NOT NULL,
    thursday INTEGER NOT NULL,
    friday INTEGER NOT NULL,
    saturday INTEGER NOT NULL,
    sunday INTEGER NOT NULL,
    start_date TEXT,
    end_date TEXT
);
CREATE TABLE calendar_dates (
    service_id TEXT NOT NULL,
    date TEXT NOT NULL,
    exception_type INTEGER NOT NULL,
    PRIMARY KEY (service_id, date)
);
"""
INDEXES = """
CREATE INDEX idx_stop_times_stop ON stop_times(stop_id, departure_sec);
CREATE INDEX idx_stop_times_trip ON stop_times(trip_id);
CREATE INDEX idx_trips_service ON trips(service_id);
CREATE INDEX idx_trips_route ON trips(route_id);
"""


class GtfsScheduleError(RuntimeError):
    """The archive or the local timetable store cannot be used."""


def parse_gtfs_time(value: Any) -> int | None:
    """Convert a GTFS ``HH:MM[:SS]`` value to seconds, including ``25:10``."""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        return None
    if hours < 0 or not 0 <= minutes <= 59 or not 0 <= seconds <= 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _normalise_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).strftime("%Y%m%d")
    except ValueError:
        return None


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def active_service_ids(
    calendar: Iterable[Any],
    exceptions: Iterable[Any],
    day: date,
) -> set[str]:
    """Return service ids active on ``day`` after calendar and exceptions.

    Dates are compared in the feed's own ``YYYYMMDD`` form. Rows with a missing
    or invalid window are skipped, never treated as active.
    """
    ymd = day.strftime("%Y%m%d")
    weekday = WEEKDAY_COLUMNS[day.weekday()]
    active: set[str] = set()
    for row in calendar:
        service_id = str(_value(row, "service_id") or "").strip()
        start = str(_value(row, "start_date") or "").strip()
        end = str(_value(row, "end_date") or "").strip()
        if not service_id or not start or not end:
            continue
        if start <= ymd <= end and int(_value(row, weekday) or 0) == 1:
            active.add(service_id)
    for row in exceptions:
        if str(_value(row, "date") or "").strip() != ymd:
            continue
        service_id = str(_value(row, "service_id") or "").strip()
        if not service_id:
            continue
        exception_type = int(_value(row, "exception_type") or 0)
        if exception_type == 1:
            active.add(service_id)
        elif exception_type == 2:
            active.discard(service_id)
    return active


def _time_label(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def _absolute(service_day: date, seconds: int) -> datetime:
    return datetime.combine(service_day, time.min, tzinfo=ISTANBUL) + timedelta(seconds=seconds)


class GtfsScheduleStore:
    """Read and atomically rebuild the local GTFS timetable database."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def metadata(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            with sqlite3.connect(str(self.path)) as connection:
                connection.execute("PRAGMA query_only=ON")
                rows = connection.execute("SELECT key, value FROM gtfs_meta").fetchall()
        except sqlite3.Error:
            return None
        if not rows:
            return None
        result: dict[str, Any] = {str(key): value for key, value in rows}
        for key in INT_META_KEYS:
            if key in result:
                try:
                    result[key] = int(result[key])
                except (TypeError, ValueError):
                    result[key] = None
        return result

    def rebuild(
        self,
        archive: bytes,
        *,
        source_url: str,
        max_rows: int = 2_500_000,
        stop_times_max_bytes: int = 128 * 1024 * 1024,
    ) -> dict[str, Any]:
        """Build a complete database and swap it in only on success."""
        if not archive.startswith(ZIP_SIGNATURES):
            raise GtfsScheduleError("source did not return a ZIP archive")
        try:
            zf = zipfile.ZipFile(io.BytesIO(archive))
        except zipfile.BadZipFile as exc:
            raise GtfsScheduleError("source returned a corrupt ZIP archive") from exc

        with zf:
            names = set(zf.namelist())
            missing = [name for name in REQUIRED_MEMBERS if name not in names]
            if missing:
                raise GtfsScheduleError(f"ZIP archive is missing {', '.join(missing)}")
            stop_times_info = zf.getinfo("stop_times.txt")
            if stop_times_info.file_size > stop_times_max_bytes:
                raise GtfsScheduleError("stop_times.txt exceeds its byte budget")

            calendar_rows = list(self._read_dicts(zf, "calendar.txt"))
            if not calendar_rows:
                raise GtfsScheduleError("calendar.txt contained no services")
            exception_rows = (
                list(self._read_dicts(zf, "calendar_dates.txt"))
                if "calendar_dates.txt" in names
                else []
            )

            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary_name = tempfile.mkstemp(
                prefix=f"{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            os.close(handle)
            temporary = Path(temporary_name)
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(str(temporary))
                connection.execute("PRAGMA journal_mode=OFF")
                connection.execute("PRAGMA synchronous=OFF")
                connection.execute("PRAGMA temp_store=MEMORY")
                connection.executescript(SCHEMA)

                stop_count = self._load_stops(connection, zf)
                route_count = self._load_routes(connection, zf)
                trip_count = self._load_trips(connection, zf)
                stop_times_rows, skipped = self._load_stop_times(
                    connection, zf, max_rows=max_rows
                )
                connection.executemany(
                    "INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            str(row.get("service_id") or "").strip(),
                            *[1 if str(row.get(day) or "").strip() == "1" else 0
                              for day in WEEKDAY_COLUMNS],
                            _normalise_date(row.get("start_date")),
                            _normalise_date(row.get("end_date")),
                        )
                        for row in calendar_rows
                        if str(row.get("service_id") or "").strip()
                    ],
                )
                exception_payload = []
                for row in exception_rows:
                    service_id = str(row.get("service_id") or "").strip()
                    exception_day = _normalise_date(row.get("date"))
                    exception_type = _int_or_none(row.get("exception_type"))
                    if (
                        service_id
                        and exception_day
                        and exception_type in (1, 2)
                    ):
                        exception_payload.append(
                            (service_id, exception_day, exception_type)
                        )
                connection.executemany(
                    "INSERT OR REPLACE INTO calendar_dates VALUES (?,?,?)",
                    exception_payload,
                )
                connection.executescript(INDEXES)

                windows = [
                    _normalise_date(row.get("end_date"))
                    for row in calendar_rows
                    if str(row.get("service_id") or "").strip()
                ]
                starts = [
                    _normalise_date(row.get("start_date"))
                    for row in calendar_rows
                    if str(row.get("service_id") or "").strip()
                ]
                calendar_end = max((value for value in windows if value), default=None)
                calendar_start = min((value for value in starts if value), default=None)
                published = max(
                    (info.date_time for info in zf.infolist()), default=None
                )
                meta = {
                    "calendar_start": _iso_date(calendar_start) or "",
                    "calendar_end": _iso_date(calendar_end) or "",
                    "built_at": datetime.now(timezone.utc).isoformat(),
                    "source_url": source_url,
                    "zip_bytes": str(len(archive)),
                    "feed_published_at": (
                        datetime(*published, tzinfo=timezone.utc).isoformat()
                        if published
                        else ""
                    ),
                    "stops_rows": str(stop_count),
                    "routes_rows": str(route_count),
                    "trips_rows": str(trip_count),
                    "stop_times_rows": str(stop_times_rows),
                    "calendar_rows": str(len(calendar_rows)),
                    "calendar_dates_rows": str(len(exception_payload)),
                    "skipped_stop_times": str(skipped),
                }
                connection.executemany(
                    "INSERT INTO gtfs_meta VALUES (?, ?)", list(meta.items())
                )
                connection.commit()
                connection.close()
                connection = None
                os.replace(temporary, self.path)
            except Exception:
                if connection is not None:
                    connection.close()
                self._remove(temporary)
                raise
            finally:
                for suffix in ("-journal", "-wal", "-shm"):
                    self._remove(Path(f"{temporary}{suffix}"))

        metadata = self.metadata()
        if metadata is None:
            # Report the underlying SQLite failure instead of a generic message;
            # the public envelope still says only that the store is unavailable.
            try:
                with sqlite3.connect(str(self.path)) as connection:
                    connection.execute("PRAGMA query_only=ON")
                    connection.execute("SELECT key, value FROM gtfs_meta LIMIT 1").fetchall()
            except sqlite3.Error as exc:
                raise GtfsScheduleError(
                    f"built timetable database is not readable: {type(exc).__name__}: {exc}"
                ) from exc
            raise GtfsScheduleError("built timetable database has no metadata rows")
        return metadata

    @staticmethod
    def _read_dicts(archive: zipfile.ZipFile, name: str) -> Iterable[dict[str, str]]:
        with archive.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            try:
                yield from csv.DictReader(text)
            finally:
                text.detach()

    @staticmethod
    def _load_stops(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> int:
        rows = []
        for row in GtfsScheduleStore._read_dicts(archive, "stops.txt"):
            stop_id = str(row.get("stop_id") or "").strip()
            if not stop_id:
                continue
            rows.append(
                (
                    stop_id,
                    (row.get("stop_name") or "").strip() or None,
                    (row.get("stop_code") or "").strip() or None,
                    _float(row.get("stop_lat")),
                    _float(row.get("stop_lon")),
                )
            )
        connection.executemany("INSERT OR REPLACE INTO stops VALUES (?,?,?,?,?)", rows)
        return len(rows)

    @staticmethod
    def _load_routes(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> int:
        rows = []
        for row in GtfsScheduleStore._read_dicts(archive, "routes.txt"):
            route_id = str(row.get("route_id") or "").strip()
            if not route_id:
                continue
            rows.append(
                (
                    route_id,
                    (row.get("route_short_name") or "").strip() or None,
                    (row.get("route_long_name") or "").strip() or None,
                    (row.get("route_type") or "").strip() or None,
                )
            )
        connection.executemany("INSERT OR REPLACE INTO routes VALUES (?,?,?,?)", rows)
        return len(rows)

    @staticmethod
    def _load_trips(connection: sqlite3.Connection, archive: zipfile.ZipFile) -> int:
        rows = []
        for row in GtfsScheduleStore._read_dicts(archive, "trips.txt"):
            trip_id = str(row.get("trip_id") or "").strip()
            route_id = str(row.get("route_id") or "").strip()
            service_id = str(row.get("service_id") or "").strip()
            if not trip_id or not route_id or not service_id:
                continue
            rows.append(
                (
                    trip_id,
                    route_id,
                    service_id,
                    (row.get("trip_headsign") or "").strip() or None,
                    (row.get("direction_id") or "").strip() or None,
                )
            )
        connection.executemany("INSERT OR REPLACE INTO trips VALUES (?,?,?,?,?)", rows)
        return len(rows)

    @staticmethod
    def _load_stop_times(
        connection: sqlite3.Connection, archive: zipfile.ZipFile, *, max_rows: int
    ) -> tuple[int, int]:
        inserted = 0
        skipped = 0
        batch: list[tuple[Any, ...]] = []
        with archive.open("stop_times.txt") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            try:
                reader = csv.reader(text)
                header = next(reader, None)
                if not header:
                    raise GtfsScheduleError("stop_times.txt has no header")
                index = {name.strip(): position for position, name in enumerate(header)}
                required = {"trip_id", "stop_id", "departure_time", "stop_sequence"}
                if not required.issubset(index):
                    raise GtfsScheduleError("stop_times.txt is missing required columns")
                for row in reader:
                    inserted += 1
                    if inserted > max_rows:
                        raise GtfsScheduleError("stop_times.txt exceeds its row budget")
                    try:
                        trip_id = row[index["trip_id"]].strip()
                        stop_id = row[index["stop_id"]].strip()
                        departure = row[index["departure_time"]].strip()
                        if not departure and "arrival_time" in index:
                            departure = row[index["arrival_time"]].strip()
                        seconds = parse_gtfs_time(departure)
                        sequence = int(row[index["stop_sequence"]].strip() or 0)
                    except (IndexError, ValueError):
                        skipped += 1
                        continue
                    if not trip_id or not stop_id or seconds is None:
                        skipped += 1
                        continue
                    pickup = (
                        row[index["pickup_type"]].strip()
                        if "pickup_type" in index and index["pickup_type"] < len(row)
                        else ""
                    )
                    batch.append((trip_id, stop_id, seconds, sequence, pickup or None))
                    if len(batch) >= 50_000:
                        connection.executemany(
                            "INSERT INTO stop_times VALUES (?,?,?,?,?)", batch
                        )
                        batch.clear()
                if batch:
                    connection.executemany("INSERT INTO stop_times VALUES (?,?,?,?,?)", batch)
            finally:
                text.detach()
        return inserted - skipped, skipped

    def find_routes(self, text: str) -> list[dict[str, Any]]:
        """Return routes whose own id or short name equals ``text``.

        Line codes are looked up exactly: ``304`` must not match ``1304``.
        """
        wanted = str(text or "").strip()
        if not wanted:
            return []
        if not self.path.exists():
            raise GtfsScheduleError("timetable database is not built")
        try:
            with sqlite3.connect(str(self.path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                rows = connection.execute(
                    "SELECT route_id, short_name, long_name, route_type FROM routes "
                    "WHERE route_id = ? COLLATE NOCASE "
                    "OR short_name = ? COLLATE NOCASE ORDER BY route_id",
                    (wanted, wanted),
                ).fetchall()
        except sqlite3.Error as exc:
            raise GtfsScheduleError("local timetable database is not readable") from exc
        return [dict(row) for row in rows]

    def route_detail(self, route_id: str) -> dict[str, Any]:
        """Return ordered stop patterns per direction for one GTFS route.

        A route can run several stop patterns in the same direction (short
        turns, loops, service variants). They are kept separate instead of
        merging into one misleading stop list. Duplicate stops inside a loop
        are preserved because ``stop_sequence`` is the ordering key.
        """
        wanted = str(route_id or "").strip()
        if not wanted:
            raise GtfsScheduleError("route_id is required")
        if not self.path.exists():
            raise GtfsScheduleError("timetable database is not built")
        try:
            with sqlite3.connect(str(self.path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                route = connection.execute(
                    "SELECT route_id, short_name, long_name, route_type FROM routes "
                    "WHERE route_id = ?",
                    (wanted,),
                ).fetchone()
                if route is None:
                    raise GtfsScheduleError("route_id is not in the GTFS route table")
                trips = connection.execute(
                    "SELECT trip_id, service_id, direction_id, headsign FROM trips "
                    "WHERE route_id = ? ORDER BY trip_id",
                    (wanted,),
                ).fetchall()
                rows = connection.execute(
                    "SELECT st.trip_id, st.stop_sequence, st.stop_id, st.departure_sec, "
                    "s.stop_name, s.stop_lat, s.stop_lon "
                    "FROM stop_times st "
                    "JOIN trips t ON t.trip_id = st.trip_id "
                    "LEFT JOIN stops s ON s.stop_id = st.stop_id "
                    "WHERE t.route_id = ? "
                    "ORDER BY st.trip_id, st.stop_sequence",
                    (wanted,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise GtfsScheduleError("local timetable database is not readable") from exc

        by_trip: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_trip.setdefault(row["trip_id"], []).append(
                {
                    "stop_sequence": row["stop_sequence"],
                    "stop_id": row["stop_id"],
                    "stop_name": row["stop_name"],
                    "stop_lat": row["stop_lat"],
                    "stop_lon": row["stop_lon"],
                    "departure_sec": row["departure_sec"],
                }
            )

        grouped: dict[str, dict[str, Any]] = {}
        for trip in trips:
            direction_id = str(trip["direction_id"] or "")
            direction = grouped.setdefault(
                direction_id,
                {"direction_id": direction_id, "trip_count": 0, "headsigns": set(),
                 "patterns": {}, "first_sec": None, "last_sec": None},
            )
            direction["trip_count"] += 1
            if trip["headsign"]:
                direction["headsigns"].add(trip["headsign"])
            stops = by_trip.get(trip["trip_id"]) or []
            if not stops:
                continue
            first_sec = stops[0]["departure_sec"]
            direction["first_sec"] = (
                first_sec if direction["first_sec"] is None
                else min(direction["first_sec"], first_sec)
            )
            direction["last_sec"] = (
                first_sec if direction["last_sec"] is None
                else max(direction["last_sec"], first_sec)
            )
            signature = tuple(stop["stop_id"] for stop in stops)
            pattern = direction["patterns"].setdefault(
                signature,
                {
                    "trip_count": 0,
                    "service_ids": set(),
                    "first_sec": first_sec,
                    "last_sec": first_sec,
                    "stops": [
                        {
                            "stop_sequence": stop["stop_sequence"],
                            "stop_id": stop["stop_id"],
                            "stop_name": stop["stop_name"],
                            "stop_lat": stop["stop_lat"],
                            "stop_lon": stop["stop_lon"],
                        }
                        for stop in stops
                    ],
                },
            )
            pattern["trip_count"] += 1
            pattern["service_ids"].add(trip["service_id"])
            pattern["first_sec"] = min(pattern["first_sec"], first_sec)
            pattern["last_sec"] = max(pattern["last_sec"], first_sec)

        directions: list[dict[str, Any]] = []
        for direction_id in sorted(grouped):
            direction = grouped[direction_id]
            patterns = []
            for pattern in direction["patterns"].values():
                patterns.append(
                    {
                        "trip_count": pattern["trip_count"],
                        "stop_count": len(pattern["stops"]),
                        "first_departure": _time_label(pattern["first_sec"]),
                        "last_departure": _time_label(pattern["last_sec"]),
                        "service_ids": sorted(pattern["service_ids"]),
                        "stops": pattern["stops"],
                    }
                )
            patterns.sort(key=lambda row: (-row["trip_count"], -row["stop_count"]))
            directions.append(
                {
                    "direction_id": direction_id,
                    "trip_count": direction["trip_count"],
                    "pattern_count": len(patterns),
                    "first_departure": (
                        _time_label(direction["first_sec"])
                        if direction["first_sec"] is not None else None
                    ),
                    "last_departure": (
                        _time_label(direction["last_sec"])
                        if direction["last_sec"] is not None else None
                    ),
                    "headsigns": sorted(direction["headsigns"]),
                    "patterns": patterns,
                }
            )

        return {
            "route_id": route["route_id"],
            "line": route["short_name"] or route["route_id"],
            "route_short_name": route["short_name"],
            "route_long_name": route["long_name"],
            "route_type": route["route_type"],
            "trip_count": len(trips),
            "directions": directions,
        }

    def departures(
        self,
        *,
        stop_id: str,
        at: datetime,
        limit: int,
        line: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return published departures at ``stop_id`` from ``at`` onwards."""
        return self.departures_at_stops(
            stop_ids=[stop_id], at=at, limit=limit, line=line
        )

    def departures_at_stops(
        self,
        *,
        stop_ids: Sequence[str],
        at: datetime,
        limit: int,
        line: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return published departures at any of ``stop_ids``, time-ordered.

        One query per service day covers every requested stop, so the merged
        answer is globally chronological instead of per-stop blocks. The current
        and previous service days are merged so GTFS times beyond ``24:00:00``
        are placed on the correct wall-clock day.
        """
        ids = [str(value).strip() for value in stop_ids if str(value).strip()]
        if not ids:
            raise GtfsScheduleError("at least one stop_id is required")
        if not self.path.exists():
            raise GtfsScheduleError("timetable database is not built")
        local = at.astimezone(ISTANBUL) if at.tzinfo else at.replace(tzinfo=ISTANBUL)
        now_seconds = local.hour * 3600 + local.minute * 60 + local.second
        rows: list[dict[str, Any]] = []
        stop_placeholders = ",".join("?" for _ in ids)
        try:
            with sqlite3.connect(str(self.path)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                found = connection.execute(
                    "SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops "
                    f"WHERE stop_id IN ({stop_placeholders})",
                    ids,
                ).fetchall()
                stops_by_id = {row["stop_id"]: row for row in found}
                missing = [sid for sid in ids if sid not in stops_by_id]
                if missing:
                    if len(ids) == 1:
                        raise GtfsScheduleError("stop_id is not in the GTFS stop table")
                    raise GtfsScheduleError(
                        "stops are not in the GTFS stop table: " + ", ".join(missing[:5])
                    )
                calendar = connection.execute(
                    "SELECT service_id, monday, tuesday, wednesday, thursday, friday, "
                    "saturday, sunday, start_date, end_date FROM calendar"
                ).fetchall()
                exceptions = connection.execute(
                    "SELECT service_id, date, exception_type FROM calendar_dates"
                ).fetchall()

                for service_day, lower_bound in (
                    (local.date(), now_seconds),
                    (local.date() - timedelta(days=1), now_seconds + 86_400),
                ):
                    services = active_service_ids(calendar, exceptions, service_day)
                    if not services:
                        continue
                    placeholders = ",".join("?" for _ in services)
                    sql = (
                        "SELECT st.trip_id, st.stop_id, st.departure_sec, st.stop_sequence, "
                        "t.route_id, t.service_id, t.headsign, t.direction_id, "
                        "r.short_name, r.long_name "
                        "FROM stop_times st "
                        "JOIN trips t ON t.trip_id = st.trip_id "
                        "LEFT JOIN routes r ON r.route_id = t.route_id "
                        f"WHERE st.stop_id IN ({stop_placeholders}) "
                        f"AND st.departure_sec >= ? "
                        f"AND COALESCE(st.pickup_type, '') <> '1' "
                        f"AND t.service_id IN ({placeholders})"
                    )
                    params: list[Any] = [*ids, lower_bound, *sorted(services)]
                    if line is not None:
                        sql += " AND (r.short_name = ? COLLATE NOCASE OR r.route_id = ? COLLATE NOCASE)"
                        params.extend([line, line])
                    sql += " ORDER BY st.departure_sec LIMIT ?"
                    params.append(limit + 1)
                    for row in connection.execute(sql, params).fetchall():
                        absolute = _absolute(service_day, int(row["departure_sec"]))
                        stop = stops_by_id[row["stop_id"]]
                        rows.append(
                            {
                                "stop_id": row["stop_id"],
                                "stop_name": stop["stop_name"],
                                "stop_lat": stop["stop_lat"],
                                "stop_lon": stop["stop_lon"],
                                "line": row["short_name"] or row["route_id"],
                                "route_id": row["route_id"],
                                "route_long_name": row["long_name"],
                                "headsign": row["headsign"],
                                "direction_id": row["direction_id"],
                                "trip_id": row["trip_id"],
                                "service_id": row["service_id"],
                                "service_date": service_day.isoformat(),
                                "stop_sequence": row["stop_sequence"],
                                "scheduled_at": absolute.isoformat(),
                                "time": absolute.strftime("%H:%M"),
                                "timetable_time": _time_label(int(row["departure_sec"])),
                                "minutes_from_now": round(
                                    (absolute - local).total_seconds() / 60, 1
                                ),
                                "realtime": False,
                                "schedule_relationship": "STATIC",
                            }
                        )
        except sqlite3.Error as exc:
            raise GtfsScheduleError("local timetable database is not readable") from exc
        rows.sort(key=lambda row: row["scheduled_at"])
        return rows

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _fetch(url: str, *, max_bytes: int | None = None) -> bytes:
    """Download the GTFS archive with the headers the source actually accepts."""
    response = httpx.get(
        url,
        headers={"Accept": GTFS_ACCEPT, "User-Agent": "izmir-mcp-gtfs-build/1"},
        timeout=GTFS_FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    content = response.content
    if max_bytes is not None and len(content) > max_bytes:
        raise GtfsScheduleError(f"archive exceeds its byte budget ({len(content)} bytes)")
    return content


def _default_database() -> Path:
    from app.core.settings import get_settings

    return Path(get_settings().gtfs_database_path)


def _default_url() -> str:
    from app.core.settings import get_settings

    return get_settings().eshot_gtfs_url


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.storage.gtfs_schedule",
        description=(
            "Build the local GTFS timetable SQLite store from the published "
            "EShot archive. Nothing is written when the archive is invalid."
        ),
    )
    parser.add_argument("--database", help="target SQLite path (default: settings)")
    parser.add_argument("--url", help="GTFS zip URL (default: settings)")
    parser.add_argument(
        "--max-bytes", type=int, default=None,
        help="reject archives larger than this many bytes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Build the store eagerly; return 0 on success, 2 on any failure."""
    args = _parser().parse_args(argv)
    database = Path(args.database) if args.database else _default_database()
    url = args.url or _default_url()
    try:
        archive = _fetch(url, max_bytes=args.max_bytes)
        metadata = GtfsScheduleStore(database).rebuild(archive, source_url=url)
    except (GtfsScheduleError, OSError, httpx.HTTPError, ValueError) as exc:
        print(f"gtfs store build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(
        "gtfs store built: "
        f"{database} stop_times_rows={metadata.get('stop_times_rows')} "
        f"calendar_start={metadata.get('calendar_start') or 'unknown'} "
        f"calendar_end={metadata.get('calendar_end') or 'unknown'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
