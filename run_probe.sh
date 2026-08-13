#!/usr/bin/env bash
# Run the probe end to end and write results.txt.
#
# Requires:
#   - python3
#   - a codag-drain binary: set CODAG_DRAIN_BIN, or have `codag-drain` on PATH.
#     Build it from https://github.com/codag-megalith/codag-drain
#       (cargo build --release -p codag-drain)
#
# Usage:
#   ./run_probe.sh
#   CODAG_DRAIN_BIN=/path/to/codag-drain ./run_probe.sh
#   PRESERVE_HIGH_SEVERITY=1 ./run_probe.sh   # run with the proposed fix on

set -euo pipefail

CODAG_DRAIN_BIN="${CODAG_DRAIN_BIN:-codag-drain}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUT_DIR="out"
DRAIN_ARGS="--format json"
if [ "${PRESERVE_HIGH_SEVERITY:-0}" = "1" ]; then
  DRAIN_ARGS="$DRAIN_ARGS --preserve-high-severity"
  echo ">>> rare critical preservation enabled"
fi

if ! command -v "$CODAG_DRAIN_BIN" >/dev/null 2>&1; then
  echo "error: $CODAG_DRAIN_BIN not found." >&2
  echo "set CODAG_DRAIN_BIN or install codag-drain (see README)." >&2
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

mkdir -p "$OUT_DIR"

echo ">>> generating logs"
"$PYTHON_BIN" generate_logs.py

echo ">>> compressing retry_storm.log"
"$CODAG_DRAIN_BIN" $DRAIN_ARGS < logs/retry_storm.log > "$OUT_DIR/retry_storm.codag.json"

echo ">>> compressing tool_needle.log"
"$CODAG_DRAIN_BIN" $DRAIN_ARGS < logs/tool_needle.log > "$OUT_DIR/tool_needle.codag.json"

echo ">>> verifying"
"$PYTHON_BIN" verify.py | tee results.txt

echo ">>> done"