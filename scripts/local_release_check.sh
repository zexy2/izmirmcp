#!/usr/bin/env bash
# Local release rehearsal: build the image, check the MCP registry label, scan
# it (trivy), produce an SBOM (syft), scan git history for secrets (gitleaks,
# redacted) and run the MCP conformance harness. Scanners run from their docker
# images, so nothing needs to be installed on the host besides docker, node and
# python. Nothing is pushed or published.
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-izmir-mcp:rehearsal}"
EXPECTED_NAME="io.github.zexy2/izmir-mcp"
TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:latest}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:latest}"
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-zricethezav/gitleaks:latest}"
OUT="out"
mkdir -p "$OUT"

step() { printf '\n==> %s\n' "$*"; }

step "docker build -t $IMAGE"
docker build -t "$IMAGE" .

step "registry label check"
label="$(docker inspect --format '{{ index .Config.Labels "io.modelcontextprotocol.server.name" }}' "$IMAGE")"
if [ "$label" != "$EXPECTED_NAME" ]; then
  echo "label mismatch: got '$label', want '$EXPECTED_NAME'" >&2
  exit 1
fi
echo "ok: $label"

step "trivy image (HIGH,CRITICAL)"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$HOME/.cache/trivy:/root/.cache/trivy" "$TRIVY_IMAGE" \
  image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$IMAGE"

step "syft SBOM -> sbom.json"
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  "$SYFT_IMAGE" "docker:$IMAGE" -o spdx-json > sbom.json
echo "sbom.json: $(wc -c < sbom.json) bytes"

step "gitleaks (full history, redacted)"
docker run --rm -v "$PWD:/repo" "$GITLEAKS_IMAGE" \
  detect --source /repo --config /repo/.gitleaks.toml --log-opts=--all --redact --no-banner \
  --report-format json --report-path /repo/$OUT/gitleaks.json

step "MCP conformance"
(cd tests/conformance && npm ci --silent)
"${PYTHON:-.venv/bin/python}" scripts/check_mcp_conformance.py --output "$OUT/conformance"

step "all checks passed"
