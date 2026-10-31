# Security and release-rehearsal report

Local rehearsal for the v0.1.0 container release, run on 2026-10-31 on branch
`release-rehearsal-and-polish` with `scripts/local_release_check.sh`.
Nothing was pushed, tagged or published. Scanners run from their official
docker images (no host install):

| Tool     | Image                  | Version |
|----------|------------------------|---------|
| trivy    | `aquasec/trivy`        | 0.76.1  |
| syft     | `anchore/syft`         | 1.55.0  |
| gitleaks | `zricethezav/gitleaks` | 8.30.1  |

## Results

| Check | Result |
|-------|--------|
| `docker build -t izmir-mcp:rehearsal .` | OK |
| Label `io.modelcontextprotocol.server.name=io.github.zexy2/izmir-mcp` | present |
| trivy, HIGH/CRITICAL, fixable only (`--ignore-unfixed`) | 0 after fix (4 before) |
| trivy, HIGH/CRITICAL, including unfixed | 44 HIGH, 0 CRITICAL (Debian 13.7 base, no upstream fix yet) |
| syft SPDX SBOM (`sbom.json`, gitignored) | 137 packages |
| gitleaks, full history (30 commits), `--redact` | no leaks (after allowlist below) |
| MCP conformance (pinned harness, 5 scenarios) | OK |

## Fixed: setuptools vendored packages

trivy flagged two HIGH CVEs, each twice (in `/opt/venv` and in the base
image's `/usr/local` interpreter), inside setuptools' `_vendor` tree:

- `jaraco.context` 5.3.0, CVE-2026-23949, fixed in 6.1.0
- `wheel` 0.45.1, CVE-2026-24049, fixed in 0.46.2

setuptools is only the build backend; nothing imports it at run time. The
Dockerfile now uninstalls it from the venv after `pip install .` and removes
`setuptools`/`wheel` from the system interpreter in the runtime stage (via
`/usr/local/bin/python -m pip`, since `PATH` points at the venv first).

## Accepted: unfixed base-image CVEs

The 44 remaining HIGH findings are Debian packages in the digest-pinned
`python:3.11-slim` base with no fixed version published. They do not block the
release; re-run the script after bumping the base digest to pick up fixes.

Re-checked on 2026-10-31: `docker buildx imagetools inspect python:3.11-slim`
still resolves to the pinned digest `sha256:673719e0…bedf60`, so there was no
base bump. Trivy 0.65.0 on the rebuilt image: 44 HIGH, 0 CRITICAL, 0 with a
fixed version. `.github/workflows/security-scan.yml` now rescans the image weekly
so upstream fixes show up without waiting for a release.

## gitleaks false positives

The first scan reported 38 `generic-api-key` hits, all in
`reports/rea-open-data-portal-evidence.json`, commit `8a4efeda`. The matched
fields (`script_key`, `from_script_key`, `key`) hold `scr_` + 64-hex content
hashes that identify captured portal scripts, not credentials.
`.gitleaks.toml` keeps the default rules and allowlists only that exact pattern
in `reports/*-evidence.json`. No secret values are recorded in this report.

## Re-running

```sh
scripts/local_release_check.sh   # writes out/ and sbom.json (both gitignored)
```
