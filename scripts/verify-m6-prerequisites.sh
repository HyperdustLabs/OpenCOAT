#!/usr/bin/env bash
# Verify M6 prerequisites P1 (pytest) and P2 (daemon RPC smoke).
# P2 live OpenClaw (Telegram/TUI) is manual — see docs/07-mvp/m6-prerequisites-status.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RPC="${OPENCOAT_RPC_URL:-http://127.0.0.1:7878/rpc}"
CONCERN_ID="${OPENCOAT_P2_CONCERN_ID:-user-shell-guard}"

echo "== P1: core tests =="
uv run pytest packages/opencoat-runtime/tests/core -q

echo "== P2: daemon reachable =="
curl -sfS "$RPC" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"health.ping","id":0}' >/dev/null

echo "== P2: seed concern (user_message) =="
curl -sfS "$RPC" -H 'Content-Type: application/json' -d "$(cat <<EOF
{
  "jsonrpc": "2.0",
  "method": "concern.upsert",
  "id": 1,
  "params": {
    "concern": {
      "id": "${CONCERN_ID}",
      "name": "User shell guard",
      "pointcut": {
        "joinpoints": ["user_message"],
        "match": { "any_keywords": ["rm", "rf", "shell"] }
      },
      "advice": {
        "type": "response_requirement",
        "content": "Do not suggest rm -rf or recursive deletes."
      }
    }
  }
}
EOF
)" >/dev/null

ROUND="run-p2-$(date +%s)"
echo "== P2: joinpoint.submit (messages[]) host_round_id=${ROUND} =="
SUBMIT=$(curl -sfS "$RPC" -H 'Content-Type: application/json' -d "$(cat <<EOF
{
  "jsonrpc": "2.0",
  "method": "joinpoint.submit",
  "id": 2,
  "params": {
    "joinpoint": {
      "id": "jp-m6-prereq-smoke",
      "level": 1,
      "name": "before_response",
      "host": "openclaw",
      "agent_session_id": "m6-prereq",
      "host_round_id": "${ROUND}",
      "ts": "2026-05-15T12:00:00+00:00",
      "payload": {
        "messages": [
          { "role": "assistant", "content": "Earlier I mentioned rm -rf in an example." },
          { "role": "user", "content": "How do I list files in shell?" }
        ]
      }
    }
  }
}
EOF
)")

python3 - "$SUBMIT" "$CONCERN_ID" <<'PY'
import json, sys
raw, concern_id = sys.argv[1], sys.argv[2]
r = json.loads(raw)
if r.get("error"):
    raise SystemExit(f"joinpoint.submit error: {r['error']}")
res = r.get("result")
if res is None:
    raise SystemExit("joinpoint.submit returned null (no weave)")
inj = res.get("injection", res) if isinstance(res, dict) else {}
items = inj.get("injections") or []
ids = [x.get("concern_id") for x in items if isinstance(x, dict)]
if concern_id not in ids:
    raise SystemExit(f"expected {concern_id} in injections, got {ids}")
print(f"  injections include {concern_id}")
PY

echo "== P2: DCN activation_log (#msg:) =="
LOG=$(curl -sfS "$RPC" -H 'Content-Type: application/json' -d "$(cat <<EOF
{
  "jsonrpc": "2.0",
  "method": "dcn.activation_log",
  "params": { "concern_id": "${CONCERN_ID}", "limit": 5 },
  "id": 3
}
EOF
)")

python3 - "$LOG" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
rows = r.get("result") or []
if not isinstance(rows, list):
    raise SystemExit(f"unexpected activation_log shape: {r}")
if not any("#msg:" in str(row.get("joinpoint_id", "")) for row in rows):
    raise SystemExit(f"no #msg: joinpoint_id in log: {rows[:3]}")
print("  activation_log contains #msg: child joinpoint id")
PY

echo "== P2: counter — user_message guard must not fire on harmless user line =="
COUNTER=$(curl -sfS "$RPC" -H 'Content-Type: application/json' -d "$(cat <<EOF
{
  "jsonrpc": "2.0",
  "method": "joinpoint.submit",
  "id": 4,
  "params": {
    "joinpoint": {
      "id": "jp-m6-prereq-counter",
      "level": 1,
      "name": "before_response",
      "host": "openclaw",
      "agent_session_id": "m6-prereq",
      "host_round_id": "run-counter-${ROUND}",
      "ts": "2026-05-15T12:00:00+00:00",
      "payload": {
        "messages": [
          { "role": "assistant", "content": "Earlier I mentioned rm -rf in an example." },
          { "role": "user", "content": "Hello" }
        ]
      }
    }
  }
}
EOF
)")

python3 - "$COUNTER" "$CONCERN_ID" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
concern_id = sys.argv[2]
res = r.get("result")
if res is None:
    print("  no injection (ok)")
    raise SystemExit(0)
inj = res.get("injection", res) if isinstance(res, dict) else {}
items = inj.get("injections") or []
ids = [x.get("concern_id") for x in items if isinstance(x, dict)]
if concern_id in ids:
    raise SystemExit(f"counter failed: {concern_id} fired on harmless user line: {ids}")
print(f"  {concern_id} did not fire on counter payload")
PY

echo ""
echo "P1 + P2 RPC smoke: PASS"
echo "Complete P2 live OpenClaw (gateway + Telegram) manually — see docs/07-mvp/m6-prerequisites-status.md"
