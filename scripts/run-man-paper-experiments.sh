#!/usr/bin/env bash
# MAN paper §8 Phase I: internal validity (H1–H5) + auxiliary experiment tables.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== fixtures (stress profile) =="
uv run python scripts/generate_morphogenetic_validation_data.py --scale stress

echo "== paper unit gates (mechanism) =="
uv run pytest \
  packages/opencoat-runtime/tests/integration/test_morphogenetic_paper_validation.py \
  packages/opencoat-runtime/tests/integration/test_morphogenetic_internal_validity.py \
  -q

echo "== Phase I internal validity (H1–H5) =="
uv run python experiments/man_paper/run.py --output "$ROOT/experiments/man_paper/results" || {
  echo "FAIL: see experiments/man_paper/results/INTERNAL_VALIDITY.md"
  exit 1
}

echo "== optional: daemon must be up for live row =="
if curl -sf "http://127.0.0.1:7878/rpc" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"health.ping","params":{}}' >/dev/null 2>&1; then
  echo "daemon: healthy"
else
  echo "daemon: not running (live row in RESULTS.md will show error)"
fi

echo "OK: Phase I -> experiments/man_paper/results/INTERNAL_VALIDITY.md"
