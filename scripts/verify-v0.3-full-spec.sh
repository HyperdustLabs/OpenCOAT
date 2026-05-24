#!/usr/bin/env bash
# v0.3 paper-spec full pipeline verification (hermetic + optional live daemon).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== v0.3 full spec: core + integration pytest =="
uv run pytest \
  packages/opencoat-runtime/tests/core/test_effector_kernel.py \
  packages/opencoat-runtime/tests/core/test_connectome_split.py \
  packages/opencoat-runtime/tests/core/test_plasticity_split.py \
  packages/opencoat-runtime/tests/core/test_plasticity_cold.py \
  packages/opencoat-runtime/tests/core/test_r_t_replay.py \
  packages/opencoat-runtime/tests/integration/test_v03_full_spec_e2e.py \
  -q

echo "== v0.3 full spec: bridge tests =="
(cd integrations/openclaw-opencoat-bridge && npm test)

if curl -sf "http://127.0.0.1:7878/rpc" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"health.ping","params":{}}' >/dev/null 2>&1; then
  echo "== v0.3 full spec: live daemon RPC =="
  curl -sf "http://127.0.0.1:7878/rpc" -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":2,"method":"credit.connectome.stats","params":{}}' | head -c 400
  echo ""
  curl -sf "http://127.0.0.1:7878/rpc" -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":3,"method":"plasticity.cold_step","params":{}}' | head -c 400
  echo ""
else
  echo "(skip live daemon — start with: opencoat runtime up)"
fi

echo "OK: v0.3 full spec verification complete"
