#!/usr/bin/env bash
# Record a scripted terminal demo of İzmir MCP via the MCP Inspector CLI.
#
#   scripts/record_demo.sh [output.cast]
#
# Uses asciinema when available, otherwise falls back to `script`. Convert a
# cast to a GIF with agg:  agg demo.cast demo.gif
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/out/demo.cast}"
mkdir -p "$(dirname "$OUT")"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
INSPECT=(npx -y @modelcontextprotocol/inspector --cli "$PY" -m app.stdio)

demo() {
  cd "$ROOT"
  run() { printf '\n$ %s\n' "$*"; sleep 1; "$@"; sleep 2; }
  run "${INSPECT[@]}" --method tools/list
  run "${INSPECT[@]}" --method prompts/list
  run "${INSPECT[@]}" --method resources/list
}

if [ "${1:-}" = "--inner" ]; then
  demo
  exit 0
fi

if command -v asciinema >/dev/null 2>&1; then
  asciinema rec --overwrite -c "$0 --inner" "$OUT"
else
  echo "asciinema not found; falling back to script(1) -> ${OUT%.cast}.log" >&2
  if script --version >/dev/null 2>&1; then
    script -q -c "$0 --inner" "${OUT%.cast}.log"  # util-linux
  else
    script -q "${OUT%.cast}.log" "$0" --inner     # BSD/macOS
  fi
fi
echo "Recorded: $OUT (GIF: agg \"$OUT\" demo.gif)"
