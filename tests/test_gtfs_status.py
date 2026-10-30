from __future__ import annotations

from pathlib import Path

import pytest

from app.core.settings import get_settings
from app.services.bus import BusService
from app.storage.gtfs_schedule import GtfsScheduleStore


class _NoNetworkApi:
    """Any network access in the status path is a bug: fail loudly."""

    async def gtfs_archive(self):
        raise AssertionError("status must not fetch the archive")

    async def stops(self):
        raise AssertionError("status must not read the stop list")

    async def arrivals(self, stop_id):
        raise AssertionError("status must not call the live arrival feed")

    async def gtfs(self):
        raise AssertionError("status must not download the GTFS zip")


@pytest.mark.asyncio
async def test_status_is_unavailable_when_no_store_exists(tmp_path: Path):
    settings = get_settings()
    service = BusService(
        settings=type(settings)(
            **{**settings.__dict__, "gtfs_database_path": str(tmp_path / "missing.sqlite3")}
        ),
        api=_NoNetworkApi(),
    )
    envelope = await service.timetable_status()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "source_unavailable"
    assert envelope["data"] == []
    joined = " ".join(envelope["warnings"]).lower()
    assert "depo" in joined or "store" in joined
    assert "boş tarife" in joined or "empty timetable" in joined


@pytest.mark.asyncio
async def test_status_reports_store_metadata_and_calendar_window(tmp_path: Path):
    db = tmp_path / "store.sqlite3"
    # Build a minimal store through the real writer so the schema is genuine.
    import sqlite3

    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE gtfs_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO gtfs_meta (key, value) VALUES (?, ?)",
            [
                ("built_at", "2026-10-28T10:00:00+00:00"),
                ("source_url", "https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip"),
                ("calendar_start", "2026-08-05"),
                ("calendar_end", "2026-10-09"),
                ("stops_rows", "11740"),
                ("routes_rows", "421"),
                ("trips_rows", "61343"),
                ("stop_times_rows", "2108736"),
            ],
        )

    settings = get_settings()
    service = BusService(
        settings=type(settings)(
            **{**settings.__dict__, "gtfs_database_path": str(db)}
        ),
        api=_NoNetworkApi(),
    )
    envelope = await service.timetable_status()
    assert envelope["ok"] is True
    row = envelope["data"][0]
    assert row["calendar_end"] == "2026-10-09"
    assert row["stop_times_rows"] == 2108736
    assert row["calendar_expired"] is True
    assert row["built_at"].startswith("2026-10-28")
    assert envelope["freshness"]["source_updated_at"] == "2026-10-09"
    joined = " ".join(envelope["warnings"]).lower()
    assert "takvim" in joined
    assert "canlı" in joined


@pytest.mark.asyncio
async def test_status_says_calendar_is_valid_when_it_has_not_expired(tmp_path: Path):
    db = tmp_path / "valid.sqlite3"
    import sqlite3

    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE gtfs_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO gtfs_meta (key, value) VALUES (?, ?)",
            [("built_at", "2026-10-28T10:00:00+00:00"), ("calendar_end", "2999-12-31")],
        )
    settings = get_settings()
    service = BusService(
        settings=type(settings)(**{**settings.__dict__, "gtfs_database_path": str(db)}),
        api=_NoNetworkApi(),
    )
    envelope = await service.timetable_status()
    assert envelope["data"][0]["calendar_expired"] is False


def test_store_metadata_survives_a_missing_file(tmp_path: Path):
    assert GtfsScheduleStore(tmp_path / "absent.sqlite3").metadata() is None
