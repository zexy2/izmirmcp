from __future__ import annotations

import asyncio
import time

import httpx
import pytest

import app.connectors.eshot as eshot_mod
import app.connectors.http as mod
from app.connectors.http import SourceError
from app.core import source_cache
from app.core.settings import Settings


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv(mod.ALLOW_PRIVATE_ENV, raising=False)
    mod.clear_host_cooldowns()
    source_cache.clear_cache()
    yield
    mod.clear_host_cooldowns()
    source_cache.clear_cache()


def _patch_transport(monkeypatch, handler):
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", patched)


def test_default_deadline_covers_every_attempt_plus_backoff():
    deadline = mod.default_total_deadline(5.0, 2)
    assert deadline >= 2 * 5.0 + mod.BACKOFF_BASE_SECONDS
    assert mod.default_total_deadline(15.0, 3) == mod.MAX_TOTAL_DEADLINE_SECONDS
    assert mod.default_total_deadline(1.0, 1) == 1.0


async def test_second_attempt_is_not_cut_off_by_deadline(monkeypatch):
    calls: list[int] = []

    async def handler(request):
        calls.append(1)
        if len(calls) == 1:
            await asyncio.sleep(0.3)  # burns a full per-attempt timeout
            raise httpx.ReadTimeout("slow", request=request)
        await asyncio.sleep(0.25)  # well inside timeout, but past the old 2×timeout
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(mod, "backoff_delay", lambda attempt: 0.0)
    _patch_transport(monkeypatch, handler)
    assert await mod.get_text("https://slow.test/x", timeout=0.3, attempts=2, max_bytes=100) == "ok"
    assert len(calls) == 2


def test_full_jitter_backoff_range():
    for attempt in range(6):
        ceiling = min(mod.BACKOFF_CAP_SECONDS, mod.BACKOFF_BASE_SECONDS * 2**attempt)
        samples = [mod.backoff_delay(attempt) for _ in range(200)]
        assert all(0.0 <= value <= ceiling for value in samples)
        assert max(samples) - min(samples) > 0  # actually jittered


async def test_backoff_sleep_counts_toward_deadline(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    monkeypatch.setattr(mod, "backoff_delay", lambda attempt: 10.0)
    _patch_transport(monkeypatch, handler)
    started = time.monotonic()
    with pytest.raises(mod.SourceTimeoutError):
        await mod._get_bytes(
            "https://slow.test/x", timeout=0.1, attempts=3, max_bytes=10, accept="*/*", total_deadline=0.3
        )
    assert time.monotonic() - started < 1.0


async def test_cooldown_needs_threshold_and_resets_on_success(monkeypatch):
    fail = {"on": True}

    def handler(request):
        if fail["on"]:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)
    for _ in range(mod.HOST_COOLDOWN_THRESHOLD - 1):
        with pytest.raises(SourceError):
            await mod.get_text("https://flaky.test/a", timeout=1, attempts=1, max_bytes=100)
    assert not mod._cooldown_active("flaky.test")
    fail["on"] = False
    assert await mod.get_text("https://flaky.test/a", timeout=1, attempts=1, max_bytes=100) == "ok"
    assert "flaky.test" not in mod._connect_failures
    fail["on"] = True
    for _ in range(mod.HOST_COOLDOWN_THRESHOLD - 1):
        with pytest.raises(SourceError):
            await mod.get_text("https://flaky.test/a", timeout=1, attempts=1, max_bytes=100)
    assert not mod._cooldown_active("flaky.test")


async def test_cooldown_counter_is_per_host_under_concurrency(monkeypatch):
    async def handler(request):
        await asyncio.sleep(0.01)
        if request.url.host == "down.test":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, text="ok")

    _patch_transport(monkeypatch, handler)
    results = await asyncio.gather(
        *[mod.get_text(f"https://{h}/x", timeout=1, attempts=1, max_bytes=100) for h in ["down.test", "up.test"] * 3],
        return_exceptions=True,
    )
    assert sum(isinstance(r, SourceError) for r in results) == 3
    assert mod._cooldown_active("down.test")
    assert not mod._cooldown_active("up.test")
    with pytest.raises(SourceError, match="temporarily unreachable"):
        await mod.get_text("https://down.test/y", timeout=1, attempts=1, max_bytes=100)


def test_per_source_settings_defaults():
    settings = Settings()
    assert settings.live_vehicle_timeout_seconds < settings.openapi_timeout_seconds
    assert settings.openapi_stale_if_error_seconds >= 3_600
    assert 60 <= settings.iztek_positions_stale_if_error_seconds <= 120


async def test_line_positions_serves_flagged_stale_copy(monkeypatch):
    payload = {"HataVarMi": False, "HatOtobusKonumlari": [{"OtobusId": 1, "KoorX": "38,4", "KoorY": "27,1", "Yon": 1}]}
    calls: list[dict] = []

    async def fake_get_json(url, **kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise SourceError("down")
        return payload

    async def no_throttle():
        return None

    clock = {"t": 1000.0}
    monkeypatch.setattr(source_cache, "_now", lambda: clock["t"])
    monkeypatch.setattr(eshot_mod, "get_json", fake_get_json)
    monkeypatch.setattr(eshot_mod, "_throttle", no_throttle)
    client = eshot_mod.EshotConnector.__new__(eshot_mod.EshotConnector)
    client.settings = Settings()
    client.iztek_base_url = "https://openapi.izmir.bel.tr/api/iztek"

    rows, info = await client.line_positions("5")
    assert info.status == "fresh" and "is_stale" not in rows[0]
    assert calls[0]["timeout"] == Settings().live_vehicle_timeout_seconds
    clock["t"] += 60
    rows, info = await client.line_positions("5")
    assert info.status == "stale" and rows[0]["is_stale"] is True
    clock["t"] += 200
    with pytest.raises(SourceError):
        await client.line_positions("5")
