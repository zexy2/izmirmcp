"""Protocol smoke: run the real server and drive the MCP wire protocol.

Deliberately network-free for data: only loopback is contacted. Unlike
``smoke_live.py`` (which exercises the service layer against live city sources),
this script proves the transport, the handshake, the advertised surface, the
envelope contract and the security guards, and it takes no external dependency.

Usage:
    .venv/bin/python scripts/smoke_mcp.py            # public mode
    .venv/bin/python scripts/smoke_mcp.py --verbose

Exit code 0 means every check passed.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = "application/json, text/event-stream"
STARTUP_BUDGET_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 15


def _opener() -> urllib.request.OpenerDirector:
    """Never let an environment proxy intercept loopback traffic."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(
    base: str,
    path: str,
    *,
    payload: dict | None = None,
    key: str | None = None,
    origin: str | None = None,
    method: str | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, dict, dict]:
    headers = {"accept": ACCEPT}
    if key:
        headers["authorization"] = f"Bearer {key}"
    if origin:
        headers["origin"] = origin
    if payload is not None:
        headers["content-type"] = "application/json"
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path, headers=headers, data=body, method=method or ("POST" if body else "GET")
    )
    try:
        with _opener().open(req, timeout=timeout) as response:
            status, raw, hdrs = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        status, raw, hdrs = exc.code, exc.read(), dict(exc.headers)
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"_raw": raw.decode("utf-8", "replace")[:300]}
    return status, parsed, {key.lower(): value for key, value in hdrs.items()}


def rpc(method: str, params: dict | None = None, *, request_id: int = 1) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def envelope_from(response: dict) -> dict:
    result = response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        # The SDK may wrap the model under a single "result" key.
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    blocks = result.get("content") or []
    for block in blocks:
        if block.get("type") == "text":
            return json.loads(block["text"])
    raise AssertionError(f"no envelope in tool result: {result}")


class Server:
    """A disposable ``python -m app.main`` process bound to an ephemeral port."""

    def __init__(self, directory: Path, extra_env: dict[str, str]):
        self.directory = directory
        self.extra_env = extra_env
        self.process: subprocess.Popen | None = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "Server":
        env = {
            "PATH": os.defpath,
            "PYTHONPATH": str(ROOT),
            "PYTHONUNBUFFERED": "1",
            "IZMIR_MCP_HOST": "127.0.0.1",
            "IZMIR_MCP_PORT": str(self.port),
            "IZMIR_MCP_DATABASE_PATH": str(self.directory / "runtime.sqlite3"),
            **self.extra_env,
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
            try:
                if request(self.base, "/healthz", timeout=1)[0] == 200:
                    return self
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(0.05)
        self.stop()
        raise RuntimeError(
            "local server did not become ready; log follows:\n"
            + log_path.read_text(encoding="utf-8", errors="replace")
        )

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __exit__(self, *_exc) -> None:
        self.stop()


class Checks:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.failures: list[str] = []
        self.passed = 0

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"  ok   {name}")
        else:
            self.failures.append(f"{name}: {detail}" if detail else name)
            print(f"  FAIL {name}" + (f": {detail}" if detail else ""))
        return condition


def public_mode(checks: Checks) -> None:
    with tempfile.TemporaryDirectory() as directory:
        with Server(Path(directory), {"IZMIR_MCP_ACCESS_LOG_ENABLED": "false"}) as server:
            base = server.base

            status, health, _ = request(base, "/healthz")
            checks.check("healthz 200", status == 200 and health.get("ok") is True, str(status))

            status, ready, _ = request(base, "/readyz")
            checks.check("readyz 200", status == 200, str(status))
            checks.check("readyz ready", ready.get("ready") is True, str(ready.get("checks")))
            checks.check(
                "readyz claims no upstream health",
                ready.get("upstream_health") == "not_checked",
                str(ready.get("upstream_health")),
            )

            status, info, _ = request(base, "/status")
            checks.check("status 200", status == 200, str(status))
            checks.check(
                "status advertises telemetry",
                isinstance(info.get("rate_limit"), dict) and isinstance(info.get("concurrency"), dict),
            )

            status, init, _ = request(base, "/mcp/", payload=rpc("initialize", {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            }))
            checks.check("initialize 200", status == 200, str(status))
            result = init.get("result") or {}
            checks.check("initialize serverInfo", bool((result.get("serverInfo") or {}).get("name")))
            checks.check("initialize instructions", bool(result.get("instructions")))

            status, tools, _ = request(base, "/mcp/", payload=rpc("tools/list", request_id=2))
            names = [tool["name"] for tool in (tools.get("result") or {}).get("tools", [])]
            checks.check("tools/list 200", status == 200, str(status))
            checks.check("tools/list non-empty", len(names) == 22, f"{len(names)} tools")
            checks.check(
                "every tool title and schema",
                all(
                    tool.get("title") and tool.get("inputSchema") and tool.get("outputSchema")
                    for tool in (tools.get("result") or {}).get("tools", [])
                ),
            )
            checks.check(
                "no tool is destructive",
                all(
                    (tool.get("annotations") or {}).get("readOnlyHint") is True
                    for tool in (tools.get("result") or {}).get("tools", [])
                ),
            )

            status, prompts, _ = request(base, "/mcp/", payload=rpc("prompts/list", request_id=3))
            checks.check(
                "prompts/list",
                status == 200 and len((prompts.get("result") or {}).get("prompts", [])) >= 6,
                str(status),
            )

            status, resources, _ = request(base, "/mcp/", payload=rpc("resources/list", request_id=4))
            uris = [item["uri"] for item in (resources.get("result") or {}).get("resources", [])]
            checks.check(
                "resources/list covers coverage/sources/schema",
                {"izmir://coverage", "izmir://sources", "izmir://schema/catalog"} <= set(uris),
                str(uris),
            )

            status, coverage, _ = request(base, "/mcp/", payload=rpc(
                "resources/read", {"uri": "izmir://coverage"}, request_id=5
            ))
            checks.check("resources/read coverage", status == 200, str(status))

            status, called, _ = request(base, "/mcp/", payload=rpc(
                "tools/call", {"name": "izmir_health", "arguments": {}}, request_id=6
            ))
            envelope = envelope_from(called) if status == 200 else {}
            checks.check(
                "tool call returns the envelope",
                status == 200
                and envelope.get("ok") is True
                and {"summary", "data", "freshness", "sources", "limits", "warnings",
                     "next_queries", "error", "result_info"} <= set(envelope),
                str(status),
            )

            # The SDK rejects a call that violates the advertised input schema
            # before our handler runs, so this is a protocol-level error rather
            # than an envelope. The tool must never be executed.
            status, invalid, _ = request(base, "/mcp/", payload=rpc(
                "tools/call", {"name": "izmir_bus_arrivals", "arguments": {}}, request_id=7
            ))
            invalid_result = invalid.get("result") or {}
            checks.check(
                "missing required argument is refused at the schema",
                status == 200
                and invalid_result.get("isError") is True
                and "stop_id" in json.dumps(invalid_result),
                json.dumps(invalid_result)[:200],
            )

            status, unknown, _ = request(base, "/mcp/", payload=rpc(
                "tools/call", {"name": "izmir_does_not_exist", "arguments": {}}, request_id=8
            ))
            unknown_result = unknown.get("result") or {}
            checks.check(
                "unknown tool is rejected",
                status >= 400
                or bool(unknown.get("error"))
                or unknown_result.get("isError") is True,
                str(status),
            )

            # A locally invalid value that passes the schema must still come back
            # as our own envelope with a typed validation_error.
            status, typed, _ = request(base, "/mcp/", payload=rpc(
                "tools/call",
                {"name": "izmir_bus_stops", "arguments": {"lat": 38.4, "lon": 27.1, "radius_m": 0}},
                request_id=9,
            ))
            typed_payload = envelope_from(typed) if status == 200 else {}
            checks.check(
                "local validation returns a typed envelope",
                typed_payload.get("ok") is False
                and (typed_payload.get("error") or {}).get("code") == "validation_error"
                and (typed_payload.get("error") or {}).get("field") == "radius_m",
                str(typed_payload.get("error")),
            )

            status, _, headers = request(
                base, "/mcp/",
                payload=rpc("tools/list", request_id=10),
                origin=None,
            )
            checks.check(
                "responses are not cached",
                headers.get("cache-control") != "public",
                headers.get("cache-control", ""),
            )


def keyed_mode(checks: Checks, key: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        env = {
            "IZMIR_MCP_API_KEYS": key,
            "IZMIR_MCP_ACCESS_LOG_ENABLED": "false",
        }
        with Server(Path(directory), env) as server:
            base = server.base

            checks.check(
                "keyed: healthz stays open",
                request(base, "/healthz")[0] == 200,
            )
            checks.check(
                "keyed: status requires a key",
                request(base, "/status")[0] == 401,
            )
            checks.check(
                "keyed: status accepts the key",
                request(base, "/status", key=key)[0] == 200,
            )
            status, _, headers = request(base, "/mcp/", payload=rpc("tools/list"))
            checks.check("keyed: mcp rejects anonymous", status == 401, str(status))
            checks.check(
                "keyed: 401 is a Bearer challenge",
                headers.get("www-authenticate", "").startswith("Bearer"),
                headers.get("www-authenticate", ""),
            )
            checks.check(
                "keyed: mcp accepts the key",
                request(base, "/mcp/", payload=rpc("tools/list", request_id=2), key=key)[0] == 200,
            )
            checks.check(
                "keyed: wrong key rejected",
                request(base, "/mcp/", payload=rpc("tools/list"), key="z" * 40)[0] == 401,
            )


def origin_guard(checks: Checks) -> None:
    with tempfile.TemporaryDirectory() as directory:
        env = {
            "IZMIR_MCP_CORS_ALLOWED_ORIGINS": "https://app.example.com",
            "IZMIR_MCP_ACCESS_LOG_ENABLED": "false",
        }
        with Server(Path(directory), env) as server:
            base = server.base
            checks.check(
                "origin: foreign origin rejected",
                request(base, "/mcp/", payload=rpc("tools/list"),
                        origin="https://evil.example.com")[0] == 403,
            )
            status, _, headers = request(
                base, "/mcp/", method="OPTIONS", origin="https://app.example.com"
            )
            checks.check(
                "origin: allowed origin preflight",
                status in {200, 204}
                and headers.get("access-control-allow-origin") == "https://app.example.com",
                f"{status} {headers.get('access-control-allow-origin')}",
            )


def stdio_mode(checks: Checks) -> None:
    """The desktop transport must handshake and list the same surface."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.stdio"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        def send(message: dict) -> dict:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("stdio returned no response: " + (process.stderr.read() or ""))
            return json.loads(line)

        init = send(rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0"},
        }))
        checks.check("stdio: initialize", bool((init.get("result") or {}).get("serverInfo")))
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        tools = send(rpc("tools/list", request_id=2))
        names = [tool["name"] for tool in (tools.get("result") or {}).get("tools", [])]
        checks.check("stdio: tools/list", len(names) == 22, f"{len(names)} tools")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every passing check")
    args = parser.parse_args()

    checks = Checks(verbose=args.verbose)

    print("public mode")
    public_mode(checks)
    print("keyed mode")
    keyed_mode(checks, "k" * 40)
    print("origin guard")
    origin_guard(checks)
    print("stdio transport")
    stdio_mode(checks)

    total = checks.passed + len(checks.failures)
    if checks.failures:
        print(f"\nFAILED {len(checks.failures)}/{total}")
        for failure in checks.failures:
            print(f"  - {failure}")
        return 1
    print(f"\nOK {checks.passed}/{total} protocol checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
