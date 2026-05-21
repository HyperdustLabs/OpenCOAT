# 09 — Queue hook dogfood (OpenClaw fork + bridge)

End-to-end dogfood for **native** `queue_before_enqueue` / `queue_after_enqueue`
on the OpenClaw fork (`opencoat/hooks-v0.1`). OpenCOAT matches
`queue.before_enqueue` and returns advice the bridge maps to OpenClaw
`{ block, prompt, summaryLine }`.

Import **one concern at a time** — all three target the same joinpoint.

## Layout

```text
examples/09_queue_hook_dogfood/
├── README.md
├── concerns/
│   ├── oc.dogfood.queue-block.json
│   ├── oc.dogfood.queue-prompt-rewrite.json
│   └── oc.dogfood.queue-summary-rewrite.json
└── scripts/
    ├── smoke-rpc.sh                 # daemon-only smoke (no gateway)
    └── live-queue-block-test.sh     # live block via gateway chat.send
```

## Prerequisites

1. OpenCOAT daemon: `opencoat runtime up`
2. OpenClaw **fork** 1:1: `./scripts/use-openclaw-fork.sh` then `./scripts/check-openclaw-fork.sh`
3. Bridge linked: `openclaw plugins install -l integrations/openclaw-opencoat-bridge`
4. Gateway restarted on fork build (≥ 2026.5.19)

## 1. RPC smoke (fast, no Telegram)

From repo root:

```bash
chmod +x examples/09_queue_hook_dogfood/scripts/smoke-rpc.sh
./examples/09_queue_hook_dogfood/scripts/smoke-rpc.sh all
```

**Pass criteria** (per case, in `result.injections[]`):

| Case | Trigger keyword | Expected `mode` | Expected `target` |
| --- | --- | --- | --- |
| block | `QUEUE_DOGFOOD_BLOCK` | `block` | `queue.prompt` |
| prompt rewrite | `QUEUE_DOGFOOD_REWRITE_PROMPT` | `rewrite` | `queue.prompt` |
| summary rewrite | `QUEUE_DOGFOOD_REWRITE_SUMMARY` | `rewrite` | `queue.summary_line` |

## 2. Import concerns

```bash
opencoat concern import examples/09_queue_hook_dogfood/concerns/oc.dogfood.queue-block.json
# or prompt / summary variant — disable others first if they share keywords
opencoat concern list | grep oc.dogfood.queue
```

## 3. Live gateway dogfood

Enable bridge logging (optional):

```json
"plugins": {
  "entries": {
    "@hyperdustlabs/opencoat-bridge": {
      "config": { "logActivations": true }
    }
  }
}
```

**Block** (automated script — preferred)

```bash
chmod +x examples/09_queue_hook_dogfood/scripts/live-queue-block-test.sh
./examples/09_queue_hook_dogfood/scripts/live-queue-block-test.sh
```

The script resolves `sessionKey` from `OPENCLAW_SESSION_ID` (default dogfood session),
starts a long run with `gateway call chat.send`, waits `WAIT_ACTIVE_SEC` (default 8),
then sends `QUEUE_DOGFOOD_BLOCK` while the first run is still active. It reads today's
gateway log under `/tmp/openclaw/openclaw-YYYY-MM-DD.log` unless `OPENCLAW_GATEWAY_LOG`
is set.

**Pass:** gateway log contains
`queue_before_enqueue→queue.before_enqueue: oc.dogfood.queue-block` and (usually) a
fresh DCN row for `oc.dogfood.queue-block`.

**Block** (manual / Telegram)

1. Import `oc.dogfood.queue-block.json`
2. Start a long reply (e.g. ask for a multi-step plan)
3. While the run is active, send: `QUEUE_DOGFOOD_BLOCK — also do X`
4. **Pass:** second message is **not** queued; gateway log may show the line above
5. **Pass:** `opencoat dcn activation-log --concern-id oc.dogfood.queue-block`

Do **not** use two sequential `openclaw agent` calls for overlap — each call blocks
until the turn finishes, so the queue hook never fires.

**Prompt rewrite**

1. Remove/disable block concern; import `oc.dogfood.queue-prompt-rewrite.json`
2. Active run + send: `QUEUE_DOGFOOD_REWRITE_PROMPT — tighten scope to Y`
3. **Pass:** follow-up is queued with rewritten prompt (check gateway debug or
   queue drain behaviour — model should see the rewritten text, not the raw line)

**Summary line rewrite**

1. Import `oc.dogfood.queue-summary-rewrite.json`
2. Active run + send: `QUEUE_DOGFOOD_REWRITE_SUMMARY — minor tweak`
3. **Pass:** queued item summary line becomes
   `OpenCOAT: queued follow-up (summary rewritten)`

## Architecture reminder

```text
OpenClaw queue_before_enqueue (sync, fork)
       │
       ▼
Bridge queue_guard → joinpoint.submit(queue.before_enqueue)
       │
       ▼
OpenCOAT weave → ConcernInjection
       │
       ▼
Bridge queueBeforeEnqueueDecision → { block | prompt | summaryLine }
       │
       ▼
OpenClaw applies before enqueue / steering
```

Poll-based `queue.before_enqueue` in `runtime-observers.ts` remains a
**fallback observe path** when the host lacks native hooks; it cannot veto.

## Related

- [Bridge README](../../integrations/openclaw-opencoat-bridge/README.md)
- [Joinpoint model §4.1](../../docs/design/opencoat-openclaw-joinpoint-model-v0.1.md#41-mvp-emit-status-bridge-integrationsopenclaw-opencoat-bridge)
- OpenCOAT PR #77 / OpenClaw fork PR #1 (queue hooks)
