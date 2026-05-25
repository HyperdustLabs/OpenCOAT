#!/usr/bin/env bash
# Phase II (H0): application learning curves + transfer. Requires Phase I first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Phase I prerequisite =="
bash scripts/run-man-paper-experiments.sh

echo "== Phase II H0 =="
uv run python experiments/man_paper/phase_ii_run.py --output "$ROOT/experiments/man_paper/results" || {
  echo "FAIL: see experiments/man_paper/results/PHASE_II_RESULTS.md"
  exit 1
}

echo "OK: Phase II -> experiments/man_paper/results/PHASE_II_RESULTS.md"
