"""Run the official MCP conformance scenarios against a real local server.

This complements ``smoke_mcp.py``: the smoke script asserts *our* contract, this
one asserts the *protocol* against the upstream ``@modelcontextprotocol/conformance``
package. Coverage is deliberately a pinned subset — the generic server
scenarios that a stateless read-only server can satisfy — and it is **not** a
certification or a full protocol audit.

Setup (one-off):
    cd tests/conformance && npm ci

Usage:
    .venv/bin/python scripts/check_mcp_conformance.py
    .venv/bin/python scripts/check_mcp_conformance.py --output /tmp/evidence
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = ROOT / "tests" / "conformance"
PROFILE = CONFORMANCE / "profile.json"
PACKAGE = CONFORMANCE / "node_modules" / "@modelcontextprotocol" / "conformance"
STARTUP_BUDGET_SECONDS = 45


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _probe(url: str) -> bool:
    try:
        with _opener().open(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, directory: Path):
        self.directory = directory
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> "Server":
        env = {
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT),
            "PYTHONUNBUFFERED": "1",
            "IZMIR_MCP_HOST": "127.0.0.1",
            "IZMIR_MCP_PORT": str(self.port),
            "IZMIR_MCP_DATABASE_PATH": str(self.directory / "conformance.sqlite3"),
            "IZMIR_MCP_ACCESS_LOG_ENABLED": "false",
        }
        log_path = self.directory / "server.log"
        with log_path.open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "app.main"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + STARTUP_BUDGET_SECONDS
        while self.process.poll() is None and time.monotonic() < deadline:
            if _probe(self.base + "/healthz"):
                return self
            time.sleep(0.05)
        self.stop()
        raise RuntimeError(
            "server did not become ready; log follows:\n" + log_path.read_text(encoding="utf-8", errors="replace")
        )

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __exit__(self, *_exc) -> None:
        self.stop()


def _read_checks(directory: Path) -> tuple[bool, int, list[str]]:
    """Missing, empty or malformed evidence fails closed."""
    reports = list(directory.rglob("checks.json"))
    if len(reports) != 1:
        return False, 0, [f"expected exactly one checks.json, found {len(reports)}"]
    try:
        checks = json.loads(reports[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, 0, [f"checks.json is unreadable: {type(exc).__name__}"]
    if not isinstance(checks, list) or not checks:
        return False, 0, ["checks.json is empty"]
    failures = [
        str(check.get("name") or check.get("id") or "?")
        for check in checks
        if not isinstance(check, dict) or check.get("status") != "SUCCESS"
    ]
    return not failures, len(checks), failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="evidence directory (must be empty)")
    args = parser.parse_args()

    if not PACKAGE.is_dir():
        print("conformance package missing; run: cd tests/conformance && npm ci", file=sys.stderr)
        return 2
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    installed = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    if installed.get("version") != profile["version"]:
        print(
            f"installed conformance {installed.get('version')} != pinned {profile['version']}; run npm ci",
            file=sys.stderr,
        )
        return 2

    output = (args.output or Path(tempfile.mkdtemp(prefix="izmir-conformance-"))).resolve()
    if output.exists() and any(output.iterdir()):
        print("output directory must be empty; existing evidence is never overwritten", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, bool, int, list[str]]] = []
    with tempfile.TemporaryDirectory(prefix="izmir-conformance-run-") as raw:
        with Server(Path(raw)) as server:
            for scenario in profile["scenarios"]:
                destination = output / scenario
                destination.mkdir()
                with (destination / "cli.log").open("w", encoding="utf-8") as log:
                    completed = subprocess.run(
                        [
                            "node",
                            str(PACKAGE / "dist" / "index.js"),
                            "server",
                            "--url",
                            server.base + "/mcp/",
                            "--scenario",
                            scenario,
                            "--output-dir",
                            str(destination),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=180,
                    )
                ok, count, failures = _read_checks(destination)
                if completed.returncode != 0 and ok:
                    # The CLI exit code is authoritative when it disagrees with
                    # the evidence file.
                    ok = False
                    failures = [f"cli exited {completed.returncode}"]
                results.append((scenario, ok, count, failures))

    summary = {
        "ok": all(ok for _name, ok, _count, _failures in results),
        "package": profile["package"],
        "version": profile["version"],
        "surface": "real python -m app.main subprocess",
        "coverage": profile["coverage"],
        "exclusions": profile.get("exclusions", []),
        "scenarios": [
            {"scenario": name, "ok": ok, "checks": count, "failures": failures} for name, ok, count, failures in results
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, ok, count, failures in results:
        status = "ok" if ok else "FAIL"
        print(f"{status:5} {name}: {count} check(s)")
        for failure in failures:
            print(f"      - {failure}")
    print(f"\nevidence: {output}")
    if not summary["ok"]:
        print("conformance FAILED")
        return 1
    print(f"conformance OK ({len(results)} scenarios)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
