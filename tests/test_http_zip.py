from __future__ import annotations

import io
import zipfile

import pytest

from app.connectors.http import SourceError, read_zip_members


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_read_zip_members_returns_only_requested_members():
    body = _zip({"stops.txt": b"stop_id\n1\n", "stop_times.txt": b"x" * 100})
    members = read_zip_members(body, max_member_bytes={"stops.txt": 1_000}, required=("stops.txt",))
    assert members == {"stops.txt": b"stop_id\n1\n"}


def test_read_zip_members_rejects_html_body():
    with pytest.raises(SourceError):
        read_zip_members(
            b"<!doctype html><html></html>",
            max_member_bytes={"stops.txt": 1_000},
            required=("stops.txt",),
        )


def test_read_zip_members_rejects_missing_required_member():
    body = _zip({"routes.txt": b"route_id\n5\n"})
    with pytest.raises(SourceError):
        read_zip_members(body, max_member_bytes={"stops.txt": 1_000}, required=("stops.txt",))


def test_read_zip_members_rejects_member_over_budget():
    body = _zip({"stops.txt": b"y" * 200})
    with pytest.raises(SourceError):
        read_zip_members(body, max_member_bytes={"stops.txt": 100}, required=("stops.txt",))


def test_read_zip_members_rejects_corrupt_archive():
    with pytest.raises(SourceError):
        read_zip_members(b"PK\x03\x04garbage", max_member_bytes={"stops.txt": 10}, required=("stops.txt",))
