# Development

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Dependencies are pinned by `uv.lock` (a universal lock for 3.11–3.13) and the
hashed `requirements.lock` (Docker image). To refresh the lock, run `uv lock`,
then regenerate `requirements.lock`.

## Tests

```bash
.venv/bin/python -m pytest -q          # offline, no network
IZMIR_LIVE=1 .venv/bin/python -m pytest -q tests/live   # live İzmir sources
.venv/bin/python scripts/smoke_mcp.py --verbose          # MCP protocol smoke
.venv/bin/python scripts/eval_tools.py                   # tool selection evals
```

Key lock-in tests:

- `tests/test_tool_compatibility.py` — existing tool names and input schemas
  must match `tests/fixtures/tool_compatibility_snapshot.json`; see
  [Tool migration](tool-migration.md).
- `tests/test_docs.py` — docs are locked against the code (tool count,
  environment variables, error codes).
- `tests/test_uptime_check.py` — the uptime probe, and that workflows use
  SHA-pinned actions.

## Scripts

Every file in `scripts/`. None of them is part of the installed package.

| Script | Purpose | Usage |
|---|---|---|
| `smoke_mcp.py` | Protocol smoke: starts the real server and drives the MCP wire protocol over loopback (handshake, surface, envelope contract, security guards). No data network calls. | `.venv/bin/python scripts/smoke_mcp.py [--verbose]` |
| `smoke_live.py` | Optional live smoke of the service layer against the real city sources. Needs network; not part of pytest. | `.venv/bin/python scripts/smoke_live.py` |
| `live_mcp_uat.py` | End-to-end user acceptance flows through the public MCP interface; checks answers are successful and honest. | `.venv/bin/python scripts/live_mcp_uat.py [--url URL] [--offline] [--verbose]` |
| `check_mcp_conformance.py` | Runs a pinned subset of the official `@modelcontextprotocol/conformance` scenarios against a local server. Not a certification. Needs `cd tests/conformance && npm ci` once. | `.venv/bin/python scripts/check_mcp_conformance.py [--output DIR]` |
| `eval_tools.py` | Reports the tool definition footprint and optionally scores external tool-selection predictions (exact match). Calls no model. | `python -m scripts.eval_tools [--predictions predictions.json]` |
| `check_release_metadata.py` | Checks that `server.json`, `app/__init__.py` and (optionally) the git tag agree. Used by `release.yml`. | `python scripts/check_release_metadata.py [--tag v0.1.0]` |
| `uptime_check.py` | Probes a public endpoint like an MCP client (`/healthz` + initialize + tools/list, with retries). Used by `uptime.yml`. Exit 0 healthy, 1 down, 2 no URL. | `python scripts/uptime_check.py --url URL [--attempts N] [--delay S] [--timeout S]` |
| `local_release_check.sh` | Local release rehearsal: builds the image, checks the registry label, runs Trivy, syft SBOM, gitleaks and the conformance harness. Pushes nothing. | `scripts/local_release_check.sh` (`IMAGE=...` to override the tag) |
| `record_demo.sh` | Records a scripted terminal demo through the MCP Inspector CLI (asciinema, or `script` as a fallback). | `scripts/record_demo.sh [output.cast]` |
| `loop.sh` | Local maintainer helper; listed in `.gitignore` and not tracked in the repository. | — |

## Lint

```bash
uvx ruff check app scripts tests   # ruff.toml; blocking in CI
uvx ruff format --check .
uvx mypy app --ignore-missing-imports   # report-only in CI for now
```

`ruff.toml` enables correctness and security rules, including all of Pyflakes
(`F`). pyupgrade (`UP`) will be enabled after its cleanup.

## CI

`.github/workflows/ci.yml` jobs: `lint`, `test` (3.11/3.12/3.13 matrix),
`conformance` (reports uploaded as artifacts), `docker` (build, `/healthz`,
Trivy scan, syft SBOM), `audit` (`pip-audit`) and a non-blocking `live` job.
All actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`)
updates them. Running locally with `act`:
[Deployment](deployment.md#running-ci-locally).

## Adding a new tool

1. The connector must go through `app/connectors/http.py` (SSRF, size and time
   limits) and use the source cache.
2. Add the tool to `app/mcp/registry.py`; do not change existing schemas.
3. Update `docs/tool-reference.md` and the README tool table.
4. Do not add the tool unless the source is genuinely open and its licence is
   clear.

## Internal records

`docs/development/` holds maintainer records: `commit-convention.md`,
`PROGRESS.md` and dated audit/evidence reports under `reports/` (including the
[security report](development/reports/security-report.md)). These are
historical working notes and are kept in the language they were written in.
