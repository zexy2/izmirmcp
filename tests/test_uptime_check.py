"""Offline tests for scripts/uptime_check.py against a real local HTTP server."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("uptime_check", ROOT / "scripts" / "uptime_check.py")
uptime_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(uptime_check)


def _serve(behaviour: dict):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, status, body, ctype="application/json", headers=None):
            raw = body.encode()
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(raw)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/healthz":
                self._send(behaviour.get("health_status", 200), json.dumps({"ok": behaviour.get("ok", True)}))
            else:
                self._send(404, "{}")

        def do_POST(self):
            msg = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if msg["method"] == "initialize":
                result = {"serverInfo": {"name": behaviour.get("name", "izmir-mcp")}}
                self._send(200, "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n\n",
                           ctype="text/event-stream", headers={"mcp-session-id": "s1"})
            else:
                behaviour["session_seen"] = self.headers.get("mcp-session-id")
                tools = behaviour.get("tools", [{"name": "izmir_status"}])
                self._send(200, json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def endpoint():
    servers = []

    def start(**behaviour):
        server, url = _serve(behaviour)
        servers.append(server)
        return url, behaviour

    yield start
    for server in servers:
        server.shutdown()


def test_healthy_endpoint_writes_github_output(endpoint, tmp_path, monkeypatch):
    url, state = endpoint()
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert uptime_check.main(["--url", url, "--attempts", "1"]) == 0
    assert "healthy=true" in out.read_text()
    assert state["session_seen"] == "s1"


@pytest.mark.parametrize(("behaviour", "fragment"), [
    ({"health_status": 503}, "HTTP"),
    ({"ok": False}, "/healthz"),
    ({"name": "other-mcp"}, "server info"),
    ({"tools": []}, "no tools"),
])
def test_unhealthy_reasons(endpoint, behaviour, fragment):
    url, _ = endpoint(**behaviour)
    reason = uptime_check.probe(url, timeout=5)
    assert reason and fragment in reason


def test_down_after_retries(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert uptime_check.main(["--url", "http://127.0.0.1:9", "--attempts", "2", "--delay", "0", "--timeout", "1"]) == 1
    assert "healthy=false" in out.read_text()


def test_no_url_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("UPTIME_URL", raising=False)
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert uptime_check.main([]) == 2
    assert "healthy=skipped" in out.read_text()


def test_rejects_non_http_scheme():
    assert "scheme" in uptime_check.probe("file:///etc/passwd")


def test_workflows_pin_actions_and_keep_permissions():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text()
        assert re.search(r"^permissions:", text, re.M), path.name
        for ref in re.findall(r"uses:\s*(\S+)", text):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{path.name}: {ref} not SHA-pinned"
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "permissions:\n  contents: read\n" in ci
    jobs = set(re.findall(r"^  ([a-z-]+):\n", ci.split("\njobs:\n", 1)[1], re.M))
    assert {"lint", "test", "conformance", "docker", "audit", "live"} <= jobs
    # Only the live job may be non-blocking at job level.
    assert re.findall(r"^    continue-on-error: true", ci, re.M) == ["    continue-on-error: true"]
    assert "IZMIR_LIVE" in ci
    assert (ROOT / ".github" / "dependabot.yml").exists()
