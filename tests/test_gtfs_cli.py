"""Run-time GTFS timetable store rebuild (``python -m app.storage.gtfs_schedule``).

A container image must not carry the ~141 MB local timetable store, so the store
has to be rebuildable from the published archive at run time. These tests use a
tiny synthetic archive and a stubbed HTTP fetch; nothing reaches the network.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.storage import gtfs_schedule
from app.storage.gtfs_schedule import GtfsScheduleError, GtfsScheduleStore

FILES = {
    "stops.txt": "stop_id,stop_name,stop_code,stop_lat,stop_lon\n"
                 "S1,Konak,101,38.4187,27.1282\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\n"
                  "R1,304,Bornova-Fahrettin Altay,3\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n"
                 "R1,WK,T1,Fahrettin Altay,0\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type\n"
                      "T1,08:00:00,08:00:00,S1,1,0\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,"
                    "sunday,start_date,end_date\n"
                    "WK,1,1,1,1,1,0,0,20260101,20261231\n",
}


def _archive(files: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in (files or FILES).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_main_builds_the_store_from_the_published_archive(tmp_path, monkeypatch, capsys):
    target = tmp_path / "store" / "izmir_mcp.sqlite3"
    monkeypatch.setattr(gtfs_schedule, "_fetch", lambda url, **_: _archive())

    exit_code = gtfs_schedule.main(
        ["--database", str(target), "--url", "https://example.test/gtfs.zip"]
    )

    assert exit_code == 0
    metadata = GtfsScheduleStore(target).metadata()
    assert metadata is not None
    assert metadata["stop_times_rows"] == 1
    assert metadata["calendar_end"] == "2026-12-31"
    assert "built" in capsys.readouterr().out.lower()


def test_main_reports_missing_members_without_writing_a_store(tmp_path, monkeypatch, capsys):
    target = tmp_path / "izmir_mcp.sqlite3"
    broken = {name: text for name, text in FILES.items() if name != "stop_times.txt"}
    monkeypatch.setattr(gtfs_schedule, "_fetch", lambda url, **_: _archive(broken))

    exit_code = gtfs_schedule.main(["--database", str(target), "--url", "https://example.test/x"])

    assert exit_code == 2
    assert not target.exists()
    assert "stop_times.txt" in capsys.readouterr().err


def test_main_reports_unreachable_source_as_failure(tmp_path, monkeypatch, capsys):
    target = tmp_path / "izmir_mcp.sqlite3"

    def explode(url, **_):
        raise OSError("connection refused")

    monkeypatch.setattr(gtfs_schedule, "_fetch", explode)

    exit_code = gtfs_schedule.main(["--database", str(target), "--url", "https://example.test/x"])

    assert exit_code == 2
    assert not target.exists()
    assert "connection refused" in capsys.readouterr().err


def test_main_does_not_fake_an_archive_when_source_returns_html(tmp_path, monkeypatch, capsys):
    target = tmp_path / "izmir_mcp.sqlite3"
    monkeypatch.setattr(gtfs_schedule, "_fetch", lambda url, **_: b"<html>nope</html>")

    exit_code = gtfs_schedule.main(["--database", str(target), "--url", "https://example.test/x"])

    assert exit_code == 2
    assert not target.exists()
    assert "ZIP" in capsys.readouterr().err


def test_main_reads_url_and_database_from_settings_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("IZMIR_MCP_DATABASE_PATH", str(tmp_path / "from-env.sqlite3"))
    monkeypatch.setenv("IZMIR_MCP_ESHOT_GTFS_URL", "https://example.test/env.zip")
    from app.core import settings as settings_module

    settings_module.get_settings.cache_clear()
    try:
        assert gtfs_schedule._default_database() == tmp_path / "from-env.sqlite3"
        assert gtfs_schedule._default_url() == "https://example.test/env.zip"
    finally:
        monkeypatch.delenv("IZMIR_MCP_DATABASE_PATH", raising=False)
        monkeypatch.delenv("IZMIR_MCP_ESHOT_GTFS_URL", raising=False)
        settings_module.get_settings.cache_clear()


def test_fetch_sends_wildcard_accept_for_eshot(monkeypatch):
    calls: list[dict] = []

    class Response:
        content = _archive()

        def __init__(self, **kwargs):
            calls.append(kwargs)

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        gtfs_schedule.httpx, "get", lambda url, **kwargs: Response(**kwargs)
    )

    gtfs_schedule._fetch("https://www.eshot.gov.tr/gtfs/bus-eshot-gtfs.zip")

    assert calls
    headers = calls[0]["headers"]
    assert headers["Accept"] == "*/*", "www.eshot.gov.tr answers 406 to open zip Accept"


def test_existing_store_is_left_untouched_on_failed_rebuild(tmp_path, monkeypatch):
    target = tmp_path / "izmir_mcp.sqlite3"
    monkeypatch.setattr(gtfs_schedule, "_fetch", lambda url, **_: _archive())
    assert gtfs_schedule.main(["--database", str(target), "--url", "https://example.test/ok"]) == 0
    before = target.read_bytes()

    monkeypatch.setattr(gtfs_schedule, "_fetch", lambda url, **_: b"<html>nope</html>")
    assert gtfs_schedule.main(["--database", str(target), "--url", "https://example.test/x"]) == 2

    assert target.read_bytes() == before


@pytest.mark.parametrize("payload", [b"", b"PK", b"not a zip"])
def test_rebuild_rejects_non_zip_payloads(tmp_path, payload):
    store = GtfsScheduleStore(tmp_path / "izmir_mcp.sqlite3")
    with pytest.raises(GtfsScheduleError):
        store.rebuild(payload, source_url="https://example.test/x")
