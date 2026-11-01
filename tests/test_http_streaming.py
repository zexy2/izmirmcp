from __future__ import annotations

import asyncio
import io
import socket
import struct
import zipfile

import httpx
import pytest

import app.connectors.http as mod
from app.connectors.http import SourceError, SourceTimeoutError


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(mod.ALLOW_PRIVATE_ENV, raising=False)
    mod.clear_host_cooldowns()
    yield
    mod.clear_host_cooldowns()


def _patch_transport(monkeypatch, handler):
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", patched)


class _CountingStream(httpx.AsyncByteStream):
    """Chunked body with no Content-Length; records how much was pulled."""

    def __init__(self, chunks: int, size: int = 65_536, delay: float = 0.0):
        self.chunks, self.size, self.delay, self.pulled = chunks, size, delay, 0

    async def __aiter__(self):
        for _ in range(self.chunks):
            if self.delay:
                await asyncio.sleep(self.delay)
            self.pulled += self.size
            yield b"x" * self.size


async def test_chunked_body_over_budget_is_rejected_without_buffering(monkeypatch):
    stream = _CountingStream(chunks=1_000)  # ~64 MB if fully read
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    with pytest.raises(SourceError, match="byte budget"):
        await mod.get_text("https://example.test/big", timeout=5, attempts=1, max_bytes=100_000)
    assert stream.pulled <= 100_000 + 2 * 65_536


async def test_slow_drip_hits_total_deadline(monkeypatch):
    stream = _CountingStream(chunks=100, size=10, delay=0.05)
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    with pytest.raises(SourceTimeoutError):
        await mod.get_text("https://example.test/drip", timeout=0.2, attempts=3, max_bytes=10_000)


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x",
        "http://[::ffff:10.0.0.1]/x",
        "http://localhost/x",
    ],
)
async def test_private_targets_refused_before_any_request(monkeypatch, location):
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(SourceError):
        await mod.get_text(location, timeout=2, attempts=1, max_bytes=1_000)
    assert calls == []


def test_ip_classification_covers_ipv6_and_mapped_forms():
    assert mod._is_public_ip("93.184.216.34")
    assert mod._is_public_ip("2606:4700::1111")
    for address in (
        "10.1.2.3",
        "100.64.0.1",
        "::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "2002:7f00:0001::",
        "fc00::1",
        "224.0.0.1",
        "0.0.0.0",
    ):
        assert not mod._is_public_ip(address), address


async def test_guarded_transport_pins_vetted_ip_and_keeps_host(monkeypatch):
    seen: list[httpx.Request] = []

    async def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    transport = mod._GuardedTransport()

    async def inner(request):
        seen.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(transport._inner, "handle_async_request", inner)
    request = httpx.Request("GET", "https://acikveri.bizizmir.com/x")
    await transport.handle_async_request(request)
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "acikveri.bizizmir.com"
    assert seen[0].extensions["sni_hostname"] == "acikveri.bizizmir.com"


@pytest.mark.parametrize("answers", [["10.0.0.5"], ["93.184.216.34", "127.0.0.1"]])
async def test_guarded_transport_rejects_rebinding_to_private(monkeypatch, answers):
    async def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in answers]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    transport = mod._GuardedTransport()

    async def inner(request):  # pragma: no cover - must not be reached
        raise AssertionError("connected to an unvetted address")

    monkeypatch.setattr(transport._inner, "handle_async_request", inner)
    with pytest.raises(SourceError, match="non-public"):
        await transport.handle_async_request(httpx.Request("GET", "https://evil.test/"))


async def test_connect_failure_puts_host_in_bounded_cooldown(monkeypatch):
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused", request=request)

    _patch_transport(monkeypatch, handler)
    for _ in range(mod.HOST_COOLDOWN_THRESHOLD):
        with pytest.raises(SourceError):
            await mod.get_text("https://down.test/a", timeout=2, attempts=3, max_bytes=1_000)
    with pytest.raises(SourceError, match="temporarily unreachable"):
        await mod.get_text("https://down.test/b", timeout=2, attempts=3, max_bytes=1_000)
    assert len(calls) == mod.HOST_COOLDOWN_THRESHOLD
    for index in range(mod.MAX_COOLDOWN_HOSTS + 50):
        mod._mark_unreachable(f"h{index}.test")
    assert len(mod._host_cooldowns) == mod.MAX_COOLDOWN_HOSTS


async def test_strict_decode_raises_lenient_replaces(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, content=b"a\xffb"))
    assert await mod.get_text("https://example.test/t", timeout=2, attempts=1, max_bytes=100) == "a\ufffdb"
    with pytest.raises(SourceError, match="UTF-8"):
        await mod.get_text("https://example.test/t", timeout=2, attempts=1, max_bytes=100, strict=True)
    with pytest.raises(SourceError):
        await mod.get_json("https://example.test/t", timeout=2, attempts=1, max_bytes=100, strict=True)


def test_eocd_forged_inside_comment_is_ignored():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(5):
            archive.writestr(f"f{index}.txt", b"x")
    real = buffer.getvalue()
    # Real EOCD says 5 entries; a fake EOCD planted in the comment claims 1.
    fake = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 1, 1, 0, 0, 0)
    body = real[:-2] + struct.pack("<H", len(fake)) + fake
    assert mod._declared_entry_count(body) == 5
    with pytest.raises(SourceError, match="entries"):
        mod.read_zip_members(body, max_member_bytes={}, max_entries=3)


def test_nat64_embedded_private_ipv4_is_not_public():
    assert not mod._is_public_ip("64:ff9b::7f00:1")
    assert not mod._is_public_ip("64:ff9b::a9fe:a9fe")
    assert mod._is_public_ip("64:ff9b::808:808")
