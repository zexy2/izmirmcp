"""Probe the public endpoint the way an MCP client does; used by the uptime workflow.

Healthy means /healthz answers {"ok": true} and an MCP initialize + tools/list
round trip succeeds. Each failed probe is retried, so one network blip on the
runner does not open an incident. Exit code 0 = healthy, 1 = down, 2 = no URL
configured. Inside GitHub Actions the result is also written to $GITHUB_OUTPUT
(healthy, reason, url).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.request
from urllib.parse import urlsplit

HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "user-agent": "izmir-mcp-uptime/1.0 (+github-actions)",
}
MAX_BODY = 1_000_000


def _decode(raw: bytes, content_type: str) -> dict:
    text = raw.decode("utf-8")
    if "text/event-stream" in content_type:
        # Streamable HTTP may answer with SSE; take the last data: frame.
        frames = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if not frames:
            raise ValueError("empty event stream")
        text = frames[-1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("response is not a JSON object")
    return value


def _request(url: str, *, timeout: float, payload: dict | None = None,
             session: str | None = None) -> tuple[int, dict, str | None]:
    data = None if payload is None else json.dumps(payload).encode()
    headers = dict(HEADERS)
    if session:
        headers["mcp-session-id"] = session
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as response:
        body = _decode(response.read(MAX_BODY), response.headers.get("content-type", ""))
        return response.status, body, response.headers.get("mcp-session-id")


def probe(base_url: str, *, timeout: float = 20.0) -> str | None:
    """Return None when healthy, otherwise a short reason."""
    base = base_url.rstrip("/")
    if urlsplit(base).scheme not in {"http", "https"}:
        return f"unsupported URL scheme: {base}"
    try:
        status, health, _ = _request(base + "/healthz", timeout=timeout)
        if status != 200 or health.get("ok") is not True:
            return f"/healthz returned HTTP {status}"
        _, init, session = _request(base + "/mcp/", timeout=timeout, payload={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "izmir-mcp-uptime", "version": "1"},
            },
        })
        name = str(init.get("result", {}).get("serverInfo", {}).get("name", ""))
        if "izmir" not in name.lower():
            return "MCP initialize did not return izmir server info"
        _, listed, _ = _request(base + "/mcp/", timeout=timeout, session=session, payload={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        if not listed.get("result", {}).get("tools"):
            return "MCP tools/list returned no tools"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _write_github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={' '.join(value.split())[:300]}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("UPTIME_URL") or "")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=20.0, help="seconds between attempts")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds per HTTP request")
    args = parser.parse_args(argv)

    if not args.url:
        print("No URL configured (set the UPTIME_URL repository variable); skipping.")
        _write_github_output(healthy="skipped", reason="no url", url="")
        return 2

    reason = None
    for attempt in range(1, max(1, args.attempts) + 1):
        reason = probe(args.url, timeout=args.timeout)
        if reason is None:
            print(f"OK: {args.url} is healthy (attempt {attempt})")
            _write_github_output(healthy="true", reason="", url=args.url)
            return 0
        print(f"attempt {attempt}/{args.attempts} failed: {reason}", file=sys.stderr)
        if attempt < args.attempts:
            time.sleep(args.delay)
    print(f"DOWN: {args.url}: {reason}")
    _write_github_output(healthy="false", reason=reason or "unknown", url=args.url)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
