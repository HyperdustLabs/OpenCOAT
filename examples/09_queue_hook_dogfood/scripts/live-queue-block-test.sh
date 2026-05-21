#!/usr/bin/env bash
# Live dogfood: active run + QUEUE_DOGFOOD_BLOCK via gateway chat.send (fork + bridge).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONCERN_BLOCK="$SCRIPT_DIR/../concerns/oc.dogfood.queue-block.json"
RPC="${OPENCOAT_RPC:-http://127.0.0.1:7878/rpc}"

SESSION_ID="${OPENCLAW_SESSION_ID:-ad9fe8a0-c144-4553-83d2-6868821ad452}"
WAIT_ACTIVE_SEC="${WAIT_ACTIVE_SEC:-8}"
NONCE="${DOGFOOD_NONCE:-$(date +%s)}"
MSG1="${MSG1:-DOGFOOD_RUN_${NONCE}: Read /Users/moss/OpenCOAT/docs/design/opencoat-openclaw-joinpoint-model-v0.1.md in five chunks (lines 1-150, 151-300, 301-450, 451-600, 601-end) using read tools only. After EACH chunk output exactly 5 bullets tagged CHUNK-N-${NONCE}. Do not finish until all five chunks are done.}"
MSG2="${MSG2:-QUEUE_DOGFOOD_BLOCK — also add: keep the answer under 200 words.}"

default_gateway_log() {
  local today
  today="$(date +%F)"
  if [[ -f "/tmp/openclaw/openclaw-${today}.log" ]]; then
    echo "/tmp/openclaw/openclaw-${today}.log"
  elif [[ -f "${HOME}/.openclaw/logs/gateway.log" ]]; then
    echo "${HOME}/.openclaw/logs/gateway.log"
  else
    echo "/tmp/openclaw/openclaw-${today}.log"
  fi
}

LOG="${OPENCLAW_GATEWAY_LOG:-$(default_gateway_log)}"
TEST_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%S)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

resolve_session_key() {
  local session_id="$1"
  openclaw sessions list --json 2>/dev/null | python3 -c '
import json
import sys

target = sys.argv[1]
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(1)
data = json.loads(raw)
rows = data if isinstance(data, list) else data.get("sessions", [])
for row in rows:
    if not isinstance(row, dict):
        continue
    sid = row.get("sessionId") or row.get("id")
    if sid == target:
        key = row.get("key") or row.get("sessionKey")
        if key:
            print(key)
            sys.exit(0)
sys.exit(1)
' "$session_id"
}

require_cmd openclaw
require_cmd curl
require_cmd python3
require_cmd opencoat

if [[ ! -f "$LOG" ]]; then
  fail "gateway log not found: $LOG (set OPENCLAW_GATEWAY_LOG)"
fi

SESSION_KEY="${OPENCLAW_SESSION_KEY:-}"
if [[ -z "$SESSION_KEY" ]]; then
  SESSION_KEY="$(resolve_session_key "$SESSION_ID")" || fail "no sessionKey for sessionId=$SESSION_ID (openclaw sessions list --json)"
fi

log_start="$(wc -l < "$LOG" | tr -d ' ')"

echo "== live queue block dogfood =="
echo "session_id=$SESSION_ID"
echo "session_key=$SESSION_KEY"
echo "gateway_log=$LOG (baseline lines=$log_start)"
echo "test_start_utc=$TEST_START_ISO"

echo "== import oc.dogfood.queue-block =="
opencoat concern import "$CONCERN_BLOCK"

PARAMS_DIR="${TMPDIR:-/tmp}/opencoat-queue-dogfood-$$"
mkdir -p "$PARAMS_DIR"
trap 'rm -rf "$PARAMS_DIR"' EXIT

python3 - "$PARAMS_DIR" "$SESSION_KEY" "$SESSION_ID" "$MSG1" "$MSG2" "$NONCE" <<'PY'
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
session_key, session_id = sys.argv[2], sys.argv[3]
msg1, msg2, nonce = sys.argv[4], sys.argv[5], sys.argv[6]

def write(name, payload):
    (out_dir / name).write_text(json.dumps(payload), encoding="utf-8")

write(
    "msg1.json",
    {
        "sessionKey": session_key,
        "sessionId": session_id,
        "message": msg1,
        "deliver": False,
        "idempotencyKey": f"dogfood-run-{nonce}",
    },
)
write(
    "msg2.json",
    {
        "sessionKey": session_key,
        "sessionId": session_id,
        "message": msg2,
        "deliver": False,
        "idempotencyKey": f"dogfood-block-{nonce}",
    },
)
PY

echo "== message 1 (chat.send, long run) =="
openclaw gateway call chat.send --json --timeout 60000 \
  --params "$(cat "$PARAMS_DIR/msg1.json")" \
  | tee "$PARAMS_DIR/msg1-response.json"

echo "== wait ${WAIT_ACTIVE_SEC}s then message 2 (block trigger) =="
sleep "$WAIT_ACTIVE_SEC"

openclaw gateway call chat.send --json --timeout 60000 \
  --params "$(cat "$PARAMS_DIR/msg2.json")" \
  | tee "$PARAMS_DIR/msg2-response.json"

sleep 2

echo "== gateway log (queue / opencoat-bridge) =="
log_slice="$(mktemp)"
tail -n +"$((log_start + 1))" "$LOG" >"$log_slice" || true
if grep -E 'queue_before_enqueue→queue\.before_enqueue: oc\.dogfood\.queue-block|queue_before_enqueue.*oc\.dogfood\.queue-block' "$log_slice" | tail -5; then
  hook_ok=true
else
  hook_ok=false
  echo "(no queue_before_enqueue activation line for oc.dogfood.queue-block)"
  grep -iE 'queue_before_enqueue|oc\.dogfood\.queue-block' "$log_slice" | tail -10 || true
fi
rm -f "$log_slice"

echo "== DCN activation (oc.dogfood.queue-block) =="
dcn_json="$(curl -sS "$RPC" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"dcn.activation_log","params":{"concern_id":"oc.dogfood.queue-block","limit":8},"id":1}')"
echo "$dcn_json" | python3 -m json.tool 2>/dev/null | head -50 || echo "$dcn_json"

dcn_ok=false
if printf '%s' "$dcn_json" | python3 -c '
import json
import sys
from datetime import datetime, timezone

threshold = sys.argv[1]
cutoff = datetime.fromisoformat(threshold.replace("Z", "+00:00"))
if cutoff.tzinfo is None:
    cutoff = cutoff.replace(tzinfo=timezone.utc)
cutoff = cutoff.timestamp() - 30

payload = json.load(sys.stdin)
for row in payload.get("result") or []:
    ts = row.get("ts", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.timestamp() >= cutoff:
            print(row.get("joinpoint_id", ""))
            sys.exit(0)
    except ValueError:
        continue
sys.exit(1)
' "$TEST_START_ISO"; then
  dcn_ok=true
fi

if [[ "$hook_ok" == true ]]; then
  echo "PASS: gateway saw queue_before_enqueue for oc.dogfood.queue-block"
else
  fail "gateway log missing queue_before_enqueue→oc.dogfood.queue-block (enable logActivations on bridge?)"
fi

if [[ "$dcn_ok" == true ]]; then
  echo "PASS: DCN activation logged during this run"
else
  echo "WARN: no DCN activation at or after $TEST_START_ISO (hook path may still be OK)"
fi

echo "== done =="
