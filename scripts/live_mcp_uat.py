"""End-to-end user acceptance flows against a running MCP server.

Unlike ``smoke_mcp.py`` (protocol contract) and ``smoke_live.py`` (service layer),
this script answers the questions a user actually asks, through the public MCP
interface, and checks that the answer is both successful and *honest*.

Usage:
    .venv/bin/python scripts/live_mcp_uat.py                  # starts a local server
    .venv/bin/python scripts/live_mcp_uat.py --url http://127.0.0.1:8000/mcp/
    .venv/bin/python scripts/live_mcp_uat.py --offline        # skip live-source flows

Exit code 0 means every flow passed.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KONAK = (38.41872, 27.12827)


@dataclass(frozen=True)
class Flow:
    question: str
    tool: str
    args: dict[str, Any]
    min_data: int = 0
    expect_ok: bool = True
    expect_error: str | None = None
    require_warning: str | None = None
    live: bool = True
    extra: tuple[str, ...] = ()


# Each flow is a question a real user would ask, tied to the tool that answers it.
CRITICAL_FLOWS: tuple[Flow, ...] = (
    Flow("Sunucu hazır mı?", "izmir_health", {}, min_data=1, live=False),
    Flow(
        "İzmir açık veri portalında otopark veri seti var mı?",
        "izmir_search_datasets", {"query": "otopark", "limit": 2}, min_data=1,
    ),
    Flow(
        "Konak çevresinde nöbetçi eczane var mı?",
        "izmir_nearby",
        {"lat": KONAK[0], "lon": KONAK[1], "types": ["pharmacy"], "radius_m": 3000, "limit": 3},
    ),
    Flow(
        "Konak çevresinde hangi ulaşım seçenekleri var?",
        "izmir_mobility_nearby",
        {"lat": KONAK[0], "lon": KONAK[1], "radius_m": 1000, "limit": 5}, min_data=1,
    ),
    Flow(
        "Konak çevresinde ESHOT durağı var mı?",
        "izmir_nearby",
        {"lat": KONAK[0], "lon": KONAK[1], "types": ["bus_stop"], "radius_m": 800, "limit": 3},
    ),
    Flow(
        "Karşıyaka'da hangi eczaneler var?",
        "izmir_nearby", {"district": "Karşıyaka", "types": ["pharmacy"], "limit": 3},
    ),
    Flow(
        "Konak Meydanı çevresinde hangi hizmetler var?",
        "izmir_city_services_nearby",
        {"place": "Konak Meydanı", "kinds": ["wifi"], "radius_m": 800, "limit": 3},
    ),
    Flow(
        "Cumartesi hangi semt pazarları kuruluyor?",
        "izmir_market_schedule", {"day": "cumartesi", "limit": 5},
    ),
    Flow(
        "Aktif ESHOT hat duyurusu var mı?",
        "izmir_transport_disruptions", {"operator": "eshot", "active_only": True, "limit": 3},
    ),
    Flow(
        "İZBAN duyuruları alınabiliyor mu?",
        "izmir_transport_disruptions", {"operator": "izban"},
        expect_ok=False, expect_error="source_unavailable", live=False,
    ),
    Flow("İZSU baraj dolulukları nasıl?", "izmir_water_status", {"limit": 3}, min_data=1),
    Flow(
        "İZSU su kesintisi verisi var mı?",
        "izmir_water_status", {"kind": "faults"},
        expect_ok=False, expect_error="source_unavailable", live=False,
    ),
    Flow("Metro istasyonları hangileri?", "izmir_transit_stations", {"mode": "metro", "limit": 5}),
    Flow("Konak durağından hangi otobüsler kalkıyor?", "izmir_bus_departures",
         {"stop_id": "10030", "at": "2026-10-05T08:00", "limit": 3}),
    Flow("Konak adıyla hangi duraklar var?", "izmir_bus_departures",
         {"stop_query": "Konak", "limit": 5}, min_data=1),
    Flow("Konak çevresindeki duraklardan hangi otobüsler kalkıyor?",
         "izmir_bus_departures",
         {"lat": KONAK[0], "lon": KONAK[1], "radius_m": 300,
          "at": "2026-10-05T08:00", "limit": 3}, min_data=1),
    Flow("304 hattı hangi duraklardan geçiyor?", "izmir_bus_routes",
         {"query": "304", "detail": True, "limit": 2}),
    Flow("Alsancak mahallesinin nüfusu kaç?", "izmir_neighborhood_profile",
         {"neighborhood": "Alsancak"}),
    Flow("Konak'ta geçmiş trafik ölçümü var mı?", "izmir_traffic_history",
         {"segment": "Konak", "limit": 3}),
    Flow("EShot durak kaynağında kaç satır var?", "izmir_datastore_query",
         {"resource_id": "0c791266-a2e4-4f14-82b8-9a9b102fbf94",
          "sql": "SELECT COUNT(*) AS n FROM records"},
         min_data=1),
    Flow("Yerel GTFS deposu hazır mı?", "izmir_gtfs_status", {}, min_data=1, live=False),
    Flow(
        "Konak durağına yaklaşan otobüs var mı?",
        "izmir_bus_arrivals", {"stop_id": "10030", "limit": 3},
    ),
    Flow(
        "Geçersiz girdi anlaşılır hata döndürüyor mu?",
        "izmir_nearby", {"lat": 38.4, "lon": 27.1, "radius_m": 0},
        expect_ok=False, expect_error="validation_error", live=False,
        extra=("repair hint",),
    ),
    Flow(
        "İzmir dışı bir koordinat dürüstçe uyarıyor mu?",
        "izmir_nearby", {"lat": 1.0, "lon": 27.1, "types": ["parking"], "radius_m": 1000},
        require_warning="İzmir il sınırları dışında", live=False,
    ),
)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(base: str, name: str, arguments: dict[str, Any], *, timeout: float = 60) -> dict:
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode()
    request = urllib.request.Request(
        base, data=body,
        headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
    )
    with _opener().open(request, timeout=timeout) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"protocol error: {payload['error']}")
    result = payload["result"]
    if result.get("isError"):
        raise RuntimeError("tool error: " + result["content"][0]["text"][:200])
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    return json.loads(result["content"][0]["text"])


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalServer:
    def __init__(self) -> None:
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}/mcp/"
        self.process: subprocess.Popen | None = None
        self.directory = tempfile.TemporaryDirectory(prefix="izmir-uat-")

    def __enter__(self) -> "LocalServer":
        env = {
            **os.environ,
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT),
            "PYTHONUNBUFFERED": "1",
            "IZMIR_MCP_HOST": "127.0.0.1",
            "IZMIR_MCP_PORT": str(self.port),
            "IZMIR_MCP_DATABASE_PATH": str(Path(self.directory.name) / "uat.sqlite3"),
            "IZMIR_MCP_CKAN_SQL_ALLOWED_RESOURCE_IDS": (
                "0c791266-a2e4-4f14-82b8-9a9b102fbf94"
            ),
            "IZMIR_MCP_ACCESS_LOG_ENABLED": "false",
        }
        log_path = Path(self.directory.name) / "server.log"
        with log_path.open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "app.main"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
        probe = f"http://127.0.0.1:{self.port}/healthz"
        deadline = time.monotonic() + 45
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                with _opener().open(probe, timeout=1) as response:
                    if response.status == 200:
                        return self
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.05)
        self.stop()
        raise RuntimeError("server did not start:\n" + log_path.read_text(errors="replace"))

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __exit__(self, *_exc) -> None:
        self.stop()
        self.directory.cleanup()


def run_flow(base: str, flow: Flow, *, offline: bool) -> tuple[bool, str]:
    if offline and flow.live:
        return True, "skipped (offline)"
    try:
        payload = call(base, flow.tool, flow.args)
    except Exception as exc:  # noqa: BLE001 - one flow must not abort the run
        return False, f"{type(exc).__name__}: {exc}"

    if payload.get("ok") != flow.expect_ok:
        return False, (
            f"ok={payload.get('ok')} (expected {flow.expect_ok}); "
            f"error={payload.get('error')}; warnings={payload.get('warnings')}"
        )
    if not flow.expect_ok:
        code = (payload.get("error") or {}).get("code")
        if flow.expect_error and code != flow.expect_error:
            return False, f"error.code={code} (expected {flow.expect_error})"
        if not payload.get("warnings"):
            return False, "an error envelope must carry a warning"
        if "repair hint" in flow.extra and not (payload.get("error") or {}).get("repair"):
            return False, "validation_error without a repair hint"
    if len(payload.get("data") or []) < flow.min_data:
        return False, f"returned {len(payload.get('data') or [])} rows, expected >= {flow.min_data}"
    if flow.require_warning:
        joined = " ".join(payload.get("warnings") or [])
        if flow.require_warning not in joined:
            return False, f"missing warning {flow.require_warning!r}"
    for key in ("summary", "data", "freshness", "sources", "limits",
                "warnings", "next_queries", "error", "result_info"):
        if key not in payload:
            return False, f"envelope missing {key!r}"
    return True, payload.get("summary", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="existing MCP endpoint (default: start a local server)")
    parser.add_argument("--offline", action="store_true", help="skip flows that need city APIs")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    failures = 0
    if args.url:
        base = args.url
        context = _nullcontext()
    else:
        context = LocalServer()
        base = None  # type: ignore[assignment]

    with context as server:
        endpoint = base or server.base
        for flow in CRITICAL_FLOWS:
            ok, detail = run_flow(endpoint, flow, offline=args.offline)
            status = "ok  " if ok else "FAIL"
            if not ok:
                failures += 1
            if args.verbose or not ok:
                print(f"{status} {flow.tool}: {flow.question}")
                print(f"     {detail}")
    total = len(CRITICAL_FLOWS)
    if failures:
        print(f"\nUAT FAILED: {failures}/{total} flows failed")
        return 1
    print(f"\nUAT OK: {total} flows passed")
    return 0


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


if __name__ == "__main__":
    sys.exit(main())
