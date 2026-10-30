"""Red-team probes: resource exhaustion, source poisoning and amplification.

Each test reproduces a concrete hostile input from the second audit round. Where
the current code is already safe the test locks that behaviour in; where it is
not, the test fails until the fix lands.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile

import pytest

from app.connectors.http import SourceError as HttpSourceError
from app.connectors.http import read_zip_members


# --- FINDING A: ZIP central-directory amplification --------------------------


def test_zip_with_huge_entry_count_is_rejected_cheaply():
    """A small archive must not cost tens of MB of memory to inspect.

    18 MB of empty entries expanded to ~113 MB and 5.6 s of CPU just to build
    ``namelist()``. A hostile or corrupted source can do this within the byte
    budget, so the entry count needs its own ceiling.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        # The required member must be present, otherwise the missing-member
        # check short-circuits and hides the amplification.
        archive.writestr("stops.txt", b"stop_id\n1\n")
        for index in range(50_000):
            archive.writestr(f"f{index}.txt", b"")
    body = buffer.getvalue()

    started = time.perf_counter()
    with pytest.raises(HttpSourceError):
        read_zip_members(body, max_member_bytes={"stops.txt": 1024 * 1024}, required=("stops.txt",))
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"inspecting 50k entries took {elapsed:.1f}s"


# --- FINDING B: CSV row amplification ----------------------------------------


def test_csv_parser_caps_the_row_count():
    """A 7.6 MB CSV produced 1M rows and 214 MB of objects.

    The parsers must stop at an advertised row budget instead of materialising
    whatever the source sends.
    """
    from app.connectors.city_layers import parse_bus_notices

    text = "HAT_NO;BASLIK;BASLAMA_TARIHI;BITIS_TARIHI\n" + "1;a;x;y\n" * 200_000
    # Refusing loudly is better than silently truncating: a capped list would
    # look complete. Either a typed error or a bounded result is acceptable;
    # materialising 200k rows is not.
    try:
        rows = parse_bus_notices(text)
    except HttpSourceError:
        return
    assert len(rows) <= 50_000, f"parsed {len(rows):,} rows without a cap"


# --- FINDING C: source poisoning raises AttributeError ------------------------


@pytest.mark.asyncio
async def test_scalar_items_in_a_source_payload_do_not_crash_the_parser():
    """A hijacked source returning ``[1, "x", null]`` must not escape as 500."""
    from app.connectors.izmir_api import IzmirOpenApi
    from app.core.settings import get_settings
    from app.core.source_cache import CacheInfo

    api = IzmirOpenApi(get_settings())

    async def stub(_path, _key):
        return [None, 1, "str", [1, 2, 3]], CacheInfo(status="fresh", retrieved_at="x")

    api._cached = stub  # type: ignore[method-assign]
    rows, _info = await api.parking()
    assert rows == []


# --- FINDING D: huge fields inflate the envelope -----------------------------


@pytest.mark.asyncio
async def test_oversized_source_field_is_truncated_not_forwarded():
    """One record with a 1 MB name made a 1.9 MB envelope, times the limit."""
    from app.connectors.izmir_api import IzmirOpenApi
    from app.core.settings import get_settings
    from app.core.source_cache import CacheInfo

    api = IzmirOpenApi(get_settings())

    async def stub(_path, _key):
        return (
            [{"ufid": "A" * 1_000_000, "name": "N" * 1_000_000, "lat": 38.4, "lng": 27.1}],
            CacheInfo(status="fresh", retrieved_at="x"),
        )

    api._cached = stub  # type: ignore[method-assign]
    rows, _info = await api.parking()
    assert rows, "the row should survive, truncated"
    assert len(str(rows[0]["name"] or "")) <= 4096
    assert len(str(rows[0]["id"] or "")) <= 256


# --- already-safe behaviour, locked in ---------------------------------------


def test_zip_bomb_is_rejected_by_the_member_budget():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("stops.txt", b"\0" * (50 * 1024 * 1024))
    with pytest.raises(HttpSourceError):
        read_zip_members(
            buffer.getvalue(),
            max_member_bytes={"stops.txt": 1024 * 1024},
            required=("stops.txt",),
        )


def test_duplicate_ids_do_not_silently_overwrite_the_index(tmp_path):
    from app.storage.geo import GeoStore, GeoStoreError

    store = GeoStore(tmp_path / "g.sqlite3")
    duplicates = [{"kind": "parking", "id": "dup", "name": f"N{i}", "lat": 38.4, "lon": 27.1} for i in range(10)]
    with pytest.raises(GeoStoreError):
        store.replace_kind("parking", duplicates)
    assert store.counts() == {}


def test_kind_filter_cannot_break_out_of_the_parameterised_query(tmp_path):
    from app.storage.geo import GeoStore

    store = GeoStore(tmp_path / "g.sqlite3")
    store.replace_kind(
        "parking",
        [
            {"kind": "parking", "id": "p", "name": "P", "lat": 38.4, "lon": 27.1},
        ],
    )
    store.replace_kind(
        "pharmacy",
        [
            {"kind": "pharmacy", "id": "f", "name": "F", "lat": 38.4, "lon": 27.1},
        ],
    )
    for payload in ("parking') OR 1=1 --", "parking' OR '1'='1", "x'; DROP TABLE geo_points--"):
        rows = store.radius(38.4, 27.1, radius_m=1000, kinds=[payload])
        assert rows == [], payload


def test_locked_database_surfaces_a_domain_error_not_a_hang(tmp_path):
    import sqlite3

    from app.storage.geo import GeoStore, GeoStoreError

    path = tmp_path / "g.sqlite3"
    store = GeoStore(path)
    store.replace_kind(
        "parking",
        [
            {"kind": "parking", "id": "p", "name": "P", "lat": 38.4, "lon": 27.1},
        ],
    )
    blocker = sqlite3.connect(path, timeout=0.1)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        started = time.perf_counter()
        with pytest.raises(GeoStoreError):
            store.radius(38.4, 27.1, radius_m=100)
        assert time.perf_counter() - started < 15
    finally:
        blocker.rollback()
        blocker.close()


def test_symlinked_database_is_not_followed_into_another_file(tmp_path):
    from app.storage.geo import GeoStore, GeoStoreError

    secret = tmp_path / "secret.txt"
    secret.write_text("SENSITIVE")
    link = tmp_path / "geo.sqlite3"
    link.symlink_to(secret)
    with pytest.raises(GeoStoreError):
        GeoStore(link).counts()
    assert secret.read_text() == "SENSITIVE"


def test_market_day_parser_is_linear_on_hostile_input():
    from app.connectors.city_layers import parse_market_days

    hostile = "cumartesi " * 50_000
    started = time.perf_counter()
    parse_market_days(hostile)
    assert time.perf_counter() - started < 2.0
