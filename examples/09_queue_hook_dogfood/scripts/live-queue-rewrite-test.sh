#!/usr/bin/env bash
# Live dogfood: active run + queue prompt/summary rewrite via gateway chat.send.
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "prompt" && "$MODE" != "summary" ]]; then
  echo "Usage: $0 <prompt|summary>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RPC="${OPENCOAT_RPC:-http://127.0.0.1:7878/rpc}"

SESSION_ID="${OPENCLAW_SESSION_ID:-ad9fe8a0-c144-4553-83d2-6868821ad452}"
WAIT_ACTIVE_SEC="${WAIT_ACTIVE_SEC:-8}"
NONCE="${DOGFOOD_NONCE:-$(date +%s)}"
MSG1="${MSG1:-DOGFOOD_RUN_${NONCE}: Read /Users/moss/OpenCOAT/docs/design/opencoat-openclaw-joinpoint-model-v0.1.md in five chunks (lines 1-150, 151-300, 301-450, 451-600, 601-end) using read tools only. After EACH chunk output exactly 5 bullets tagged CHUNK-N-${NONCE}. Do not finish until all five chunks are done.}"

if [[ "$MODE" == "prompt" ]]; then
  CONCERN_FILE="$SCRIPT_DIR/../concerns/oc.dogfood.queue-prompt-rewrite.json"
  CONCERN_ID="oc.dogfood.queue-prompt-rewrite"
  MSG2="${MSG2:-QUEUE_DOGFOOD_REWRITE_PROMPT — tighten scope: keep the answer under 200 words.}"
else
  CONCERN_FILE="$SCRIPT_DIR/../concerns/oc.dogfood.queue-summary-rewrite.json"
  CONCERN_ID="oc.dogfood.queue-summary-rewrite"
  MSG2="${MSG2:-QUEUE_DOGFOOD_REWRITE_SUMMARY — minor tweak only.}"
fi

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

command -v openclaw >/dev/null || fail "missing openclaw"
command -v curl >/dev/null || fail "missing curl"
command -v python3 >/dev/null || fail "missing python3"
command -v opencoat >/dev/null || fail "missing opencoat"
[[ -f "$LOG" ]] || fail "gateway log not found: $LOG"

SESSION_KEY="${OPENCLAW_SESSION_KEY:-}"
if [[ -z "$SESSION_KEY" ]]; then
  SESSION_KEY="$(resolve_session_key "$SESSION_ID")" || fail "no sessionKey for sessionId=$SESSION_ID"
fi

log_start="$(wc -l < "$LOG" | tr -d ' ')"

echo "== live queue ${MODE} rewrite dogfood =="
echo "concern_id=$CONCERN_ID"
echo "session_key=$SESSION_KEY"
echo "gateway_log=$LOG (baseline lines=$log_start)"

echo "== import ${CONCERN_ID} =="
opencoat concern import "$CONCERN_FILE"

PARAMS_DIR="${TMPDIR:-/tmp}/opencoat-queue-dogfood-$$"
mkdir -p "$PARAMS_DIR"
trap 'rm -rf "$PARAMS_DIR"' EXIT

python3 - "$PARAMS_DIR" "$SESSION_KEY" "$SESSION_ID" "$MSG1" "$MSG2" "$NONCE" "$MODE" <<'PY'
import json
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
session_key, session_id = sys.argv[2], sys.argv[3]
msg1, msg2, nonce, mode = sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7]

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
        "idempotencyKey": f"dogfood-{mode}-{nonce}",
    },
)
PY

openclaw gateway call chat.send --json --timeout 60000 \
  --params "$(cat "$PARAMS_DIR/msg1.json")" | tee "$PARAMS_DIR/msg1-response.json"

echo "== wait ${WAIT_ACTIVE_SEC}s then rewrite trigger =="
sleep "$WAIT_ACTIVE_SEC"

openclaw gateway call chat.send --json --timeout 60000 \
  --params "$(cat "$PARAMS_DIR/msg2.json")" | tee "$PARAMS_DIR/msg2-response.json"

sleep 2

log_slice="$(mktemp)"
tail -n +"$((log_start + 1))" "$LOG" >"$log_slice" || true
hook_ok=false
if grep -E "queue_before_enqueue→queue\\.before_enqueue: ${CONCERN_ID}|queue_before_enqueue.*${CONCERN_ID}" "$log_slice" | tail -5; then
  hook_ok=true
else
  echo "(no queue_before_enqueue line for ${CONCERN_ID})"
  grep -iE 'queue_before_enqueue' "$log_slice" | tail -10 || true
fi
rm -f "$log_slice"

dcn_json="$(curl -sS "$RPC" -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"dcn.activation_log\",\"params\":{\"concern_id\":\"${CONCERN_ID}\",\"limit\":8},\"id\":1}")"

dcn_ok=false
if printf '%s' "$dcn_json" | python3 -c '
import json, sys
from datetime import datetime, timezone
cutoff = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
if cutoff.tzinfo is None:
    cutoff = cutoff.replace(tzinfo=timezone.utc)
cutoff = cutoff.timestamp() - 30
for row in json.load(sys.stdin).get("result") or []:
    try:
        dt = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if dt.timestamp() >= cutoff:
            sys.exit(0)
    except (KeyError, ValueError):
        pass
sys.exit(1)
' "$TEST_START_ISO"; then
  dcn_ok=true
fi

[[ "$hook_ok" == true ]] || fail "gateway log missing queue_before_enqueue→${CONCERN_ID}"
echo "PASS: gateway saw queue_before_enqueue for ${CONCERN_ID}"
[[ "$dcn_ok" == true ]] && echo "PASS: DCN activation during run" || echo "WARN: no fresh DCN row (check daemon)"
