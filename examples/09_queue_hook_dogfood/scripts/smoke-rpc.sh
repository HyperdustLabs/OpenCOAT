#!/usr/bin/env bash
# Smoke-test queue.before_enqueue via daemon RPC (no OpenClaw gateway required).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONCERNS_DIR="$SCRIPT_DIR/../concerns"
RPC="${OPENCOAT_RPC:-http://127.0.0.1:7878/rpc}"

usage() {
  cat <<'EOF'
Usage: smoke-rpc.sh <block|prompt|summary|all>

Imports the matching dogfood concern (if daemon is up), submits a synthetic
queue.before_enqueue joinpoint, and prints the ConcernInjection JSON.

Examples:
  ./examples/09_queue_hook_dogfood/scripts/smoke-rpc.sh block
  ./examples/09_queue_hook_dogfood/scripts/smoke-rpc.sh all
EOF
}

mode="${1:-}"
if [[ -z "$mode" ]]; then
  usage
  exit 2
fi

rpc() {
  curl -sS "$RPC" -H 'Content-Type: application/json' -d "$1"
}

import_concern() {
  local file="$1"
  if ! command -v opencoat >/dev/null 2>&1; then
    echo "skip import ($file): opencoat CLI not on PATH" >&2
    return 0
  fi
  opencoat concern import "$file" || true
}

submit_queue() {
  local prompt="$1"
  local summary_line="$2"
  local id="$3"
  # Keyword matcher reads text/raw_text (see pointcut/_text.py); mirror bridge queuePayload JSON.
  local prompt_json
  prompt_json=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$prompt")
  local summary_json
  summary_json=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$summary_line")
  rpc "$(cat <<EOF
{
  "jsonrpc": "2.0",
  "method": "joinpoint.submit",
  "id": 1,
  "params": {
    "joinpoint": {
      "id": "jp-smoke-queue-${id}",
      "level": 1,
      "name": "queue.before_enqueue",
      "host": "openclaw",
      "agent_session_id": "dogfood-queue",
      "host_round_id": "run-smoke-${id}",
      "ts": "2026-05-19T12:00:00+00:00",
      "payload": {
        "stage": "before_enqueue",
        "queue_key": "main",
        "queue_mode": "followup",
        "depth_before": 0,
        "prompt": ${prompt_json},
        "summary_line": ${summary_json},
        "text": ${prompt_json},
        "raw_text": ${prompt_json},
        "session_key": "agent:main:main"
      }
    }
  }
}
EOF
)" | python3 -m json.tool
}

run_case() {
  local name="$1"
  local concern_file="$2"
  local prompt="$3"
  local summary="$4"
  echo "=== smoke: $name ==="
  import_concern "$concern_file"
  submit_queue "$prompt" "$summary" "$name"
  echo
}

case "$mode" in
  block)
    run_case block "$CONCERNS_DIR/oc.dogfood.queue-block.json" \
      "QUEUE_DOGFOOD_BLOCK please queue this" "user follow-up"
    ;;
  prompt)
    run_case prompt "$CONCERNS_DIR/oc.dogfood.queue-prompt-rewrite.json" \
      "QUEUE_DOGFOOD_REWRITE_PROMPT add constraint X" "user follow-up"
    ;;
  summary)
    run_case summary "$CONCERNS_DIR/oc.dogfood.queue-summary-rewrite.json" \
      "QUEUE_DOGFOOD_REWRITE_SUMMARY short note" "original summary line"
    ;;
  all)
    run_case block "$CONCERNS_DIR/oc.dogfood.queue-block.json" \
      "QUEUE_DOGFOOD_BLOCK please queue this" "user follow-up"
    run_case prompt "$CONCERNS_DIR/oc.dogfood.queue-prompt-rewrite.json" \
      "QUEUE_DOGFOOD_REWRITE_PROMPT add constraint X" "user follow-up"
    run_case summary "$CONCERNS_DIR/oc.dogfood.queue-summary-rewrite.json" \
      "QUEUE_DOGFOOD_REWRITE_SUMMARY short note" "original summary line"
    ;;
  *)
    usage
    exit 2
    ;;
esac
