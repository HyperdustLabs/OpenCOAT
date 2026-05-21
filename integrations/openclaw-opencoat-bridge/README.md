# OpenCOAT ↔ OpenClaw bridge

TypeScript **OpenClaw gateway plugin** that forwards real agent hooks to the
OpenCOAT daemon (`joinpoint.submit` over HTTP JSON-RPC) and folds
`ConcernInjection` advice back into the prompt / tool path.

This closes the gap left by `opencoat plugin install openclaw` (Python scaffold
only): OpenClaw loads **npm/TS extensions** from `~/.openclaw/extensions/`, not
the generated `opencoat_plugin/` folder.

## Hook → joinpoint mapping

The bridge registers **28** OpenClaw plugin hooks (`hook-bindings.ts`), including
the OpenCOAT fork's native queue hooks.
Skipped: `before_message_write`, `tool_result_persist` (sync hot path — cannot await daemon RPC),
`before_install` (install-only).

| OpenClaw hook | OpenCOAT joinpoint | Effect |
| --- | --- | --- |
| `session_start` | `runtime_start` | submit (observe) |
| `session_end` | `runtime_stop` | submit |
| `gateway_start` / `gateway_stop` | `runtime_start` / `runtime_stop` | submit (level 0) |
| `before_reset` | `runtime_recovery` | submit |
| `message_received` | `on_user_input` | submit + buffer; optional `extract_from_chat` |
| `inbound_claim` / `before_dispatch` | `on_user_input` | submit |
| `before_prompt_build` | `before_response` | submit + **`prependSystemContext`** |
| `before_agent_start` | `before_reasoning` | submit |
| `before_agent_reply` / `reply_dispatch` | `before_response` | submit |
| `llm_input` | `before_reasoning` | submit |
| `llm_output` | `after_reasoning` | submit |
| `agent_end` / `message_sent` | `after_response` | submit |
| `message_sending` | `before_response` | submit + **`cancel`** when BLOCK advice |
| `before_tool_call` | `before_tool_call` | submit + **`block`** / param guard |
| `after_tool_call` | `after_tool_call` | submit (DCN activation) |
| `queue_before_enqueue` | `queue.before_enqueue` | submit + **`block`** / queue prompt rewrite |
| `queue_after_enqueue` | `queue.after_enqueue` | submit (observe) |
| `before_compaction` / `after_compaction` | `before_memory_write` / `after_memory_write` | submit |
| `subagent_spawning` | `task.before_create` | submit + **`status: error`** when BLOCK |
| `subagent_delivery_target` / `subagent_spawned` | `task.after_create` | submit |
| `subagent_ended` | `task.before_terminal` | submit |
| `before_model_resolve` | `before_reasoning` | submit |

### Runtime observers (no extra OpenClaw plugin hooks)

When `runtimeObservers` is true (default), the bridge also subscribes to host surfaces
that are **not** `api.on` plugin hooks:

| Source | Joinpoints emitted | Notes |
| --- | --- | --- |
| `api.runtime.events.onAgentEvent` | `reply_run.before_begin`, `reply_run.phase.running`, `planning.plan_updated`, `approval.requested`, compaction → memory JPs | Lifecycle `start` ≈ run begin; first assistant/tool/item after start ≈ `running` |
| `api.registerHook` `session:compact:*` | `before_memory_write` / `after_memory_write` | Same boundary as plugin compaction hooks |
| Poll `getFollowupQueueDepth` (host dist) | `queue.before_enqueue`, `queue.before_collect` | Fallback for OpenClaw builds without native queue hooks; depth diff per tracked `sessionKey` |
| Poll `api.runtime.tasks.runs.bindSession().list()` | `task.before_create`, `task.after_create`, `task.before_terminal` | First sight + status transitions (incl. non-subagent `createTaskRecord`) |

Tracked sessions: any hook `ctx.sessionKey` plus agent events. Poll interval: `observerPollMs` (default 500).

Pointcuts may use legacy names (`before_tool_call`) or v0.1 aliases (`tool.before_call`) — see ADR-0011.


## Prerequisites

1. Daemon running: `opencoat runtime up`
2. Concerns in the daemon store: `opencoat concern extract …` and/or `opencoat concern import --demo`
3. **OpenClaw fork (required for queue hooks):** global CLI and gateway must be **1:1**
   with `~/openclaw-fork` (branch `opencoat/hooks-v0.1`). From OpenCOAT repo root:
   `./scripts/use-openclaw-fork.sh` then `./scripts/check-openclaw-fork.sh`.
   See [openclaw-fork-dev.md](../../docs/guides/openclaw-fork-dev.md). Do **not** use
   npm registry `openclaw` or upstream `~/openclaw` for bridge dogfood.
4. OpenClaw gateway **≥ 2026.5.19** (fork) with plugin prompt injection allowed
5. **Optional — B.AI for both daemon and OpenClaw chat:** see [`docs/config/bai-llm.md`](../../docs/config/bai-llm.md#openclaw--bai)

## Install (recommended)

From the COAT repo (builds TS, links into `~/.openclaw/extensions/`, merges config):

```bash
openclaw plugins install -l /path/to/COAT/integrations/openclaw-opencoat-bridge
openclaw gateway restart
```

OpenClaw requires scoped plugin ids in `**@scope/name**` form. The on-disk folder is
flat (no slash), e.g. `~/.openclaw/extensions/@hyperdustlabs-opencoat-bridge`.

Verify:

```bash
openclaw plugins list   # @hyperdustlabs/opencoat-bridge → loaded
grep opencoat-bridge ~/.openclaw/logs/gateway.log   # [opencoat-bridge] registered
```

Alternative helper (same symlink + `openclaw.json` merge):

```bash
./integrations/openclaw-opencoat-bridge/scripts/install-local.sh
openclaw plugins install -l /path/to/COAT/integrations/openclaw-opencoat-bridge
openclaw gateway restart
```

Manual `plugins.entries` key must be `**@hyperdustlabs/opencoat-bridge**` (with slash),
not `@hyperdustlabs-opencoat-bridge`. Remove legacy `@hyperdust/*` entries. Set
`hooks.allowPromptInjection=true`, `hooks.allowConversationAccess=true`, and
`daemonUrl` in plugin config (not `process.env` in the plugin — OpenClaw blocks
env+network patterns at install time).

## Verify

1. Chat in OpenClaw (Telegram / CLI) with text that matches your concern keywords, e.g. `Never run rm -rf in shell.`
2. Check DCN activations (should **not** be only `jp-manual-`*):

```bash
curl -sS http://127.0.0.1:7878/rpc -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"dcn.activation_log","params":{"limit":10},"id":1}' \
  | python3 -m json.tool
```

1. Gateway logs should include `[opencoat-bridge] registered` and optional activation lines when `logActivations` is true.

## Configuration


| Field                  | Default                     | Description                                                                 |
| ---------------------- | --------------------------- | --------------------------------------------------------------------------- |
| `daemonUrl`            | `http://127.0.0.1:7878/rpc` | JSON-RPC endpoint (set in `plugins.entries` config)                         |
| `enabled`              | `true`                      | Set `false` to no-op (hooks still register)                                 |
| `logActivations`       | `false`                     | Log matched concern ids per joinpoint                                       |
| `extractOnUserMessage` | `false`                     | Run `concern.extract` on user chat via `joinpoint.submit` before weave (LLM) |
| `runtimeObservers`     | `true`                      | Agent events + queue/task poll + internal compact hooks                    |
| `observerPollMs`       | `500`                       | Queue/task poll interval (ms, min 100)                                       |


## Prompt-code / messages passthrough

`before_prompt_build` forwards the hook’s `messages[]` (OpenAI-style roles and
`content`) on the joinpoint payload so the daemon can run **JoinpointDiscovery**
(message / `runtime_prompt.*` section joinpoints). `message_received` sends a
single `{ role: "user", content }` row the same way.

Keyword pointcuts still work: flattened text is duplicated in `text` /
`raw_text` for matchers that do not yet target `user_message`.

## User stories


| ID       | Story                                                                                                                                                                                                         | Acceptance                                                                                                                                                                                 |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **US-1** | As an **OpenClaw operator**, I want the gateway bridge to pass `**messages[]`** on `before_prompt_build`, so that the daemon can discover **message-level joinpoints** without me emitting one RPC per row.   | Payload includes `messages`; daemon expands `user_message` / `assistant_message`; DCN activations can show ids like `jp-oc-…#msg:0`.                                                       |
| **US-2** | As a **policy author**, I want concerns to target `**user_message`** only, so that **assistant history** in the same prompt does not false-trigger keyword guards.                                            | Concern with `joinpoints: ["user_message"]` + keywords weaves on user lines only; same keywords on `before_response` alone can still match flattened history (documented counter-example). |
| **US-3** | As a **platform engineer**, I want **one** `joinpoint.submit` per prompt build, so that I keep OpenClaw hooks thin while OpenCOAT performs **JoinpointDiscovery** (AOP (AspectJ) surface → many join points). | Bridge calls submit once per `before_prompt_build`; runtime merges injections; host still only `prependSystemContext` at coarse boundary.                                                  |
| **US-4** | As an **auditor**, I want activations tied to **stable child joinpoint ids** (`parent#msg:N`), so that I can tell which message row triggered a concern in replay and DCN logs.                               | `dcn.activation_log` shows `joinpoint_id` suffix `#msg:` / `#sec:` after a live or smoke submit with `messages`.                                                                           |


Narrative walkthrough for **US-2** (setup + curl + live chat): see the use case below.

## Use case: only weave on the **user** line (not the whole transcript)

**Problem.** A concern with `joinpoints: ["before_response"]` and
`match.any_keywords: ["rm", "shell"]` scans the **flattened** prompt text. If the
assistant’s earlier reply already mentioned `rm -rf`, the next turn can false-positive
even when the user’s new message is harmless.

**Approach.** Point at the `**user_message`** joinpoint (message layer). The bridge
sends structured `messages[]`; the daemon expands one coarse `before_response`
submit into per-role joinpoints — you do not emit each one from TypeScript.

```text
OpenClaw before_prompt_build
  messages: [ system, user, assistant, user ]
       │
       ▼
Bridge payload: { text, raw_text, messages: [...] }
       │
       ▼
Daemon JoinpointDiscovery (one joinpoint.submit)
  before_response          ← lifecycle (optional match)
  user_message  (×2)     ← one JP per user row
  assistant_message        ← per assistant row
  system_message           ← per system row
       │
       ▼
Pointcut joinpoints: ["user_message"]  →  only user rows activate
```

### 1. Seed a message-level concern

```bash
opencoat runtime up

curl -sS http://127.0.0.1:7878/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0",
  "method": "concern.upsert",
  "id": 1,
  "params": {
    "concern": {
      "id": "user-shell-guard",
      "name": "User shell guard",
      "description": "Warn when the user asks for destructive shell",
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
}'
```

### 2. Simulate what the bridge sends (smoke test without Telegram)

Same shape as `before_prompt_build` after messages passthrough:

```bash
curl -sS http://127.0.0.1:7878/rpc -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0",
  "method": "joinpoint.submit",
  "id": 2,
  "params": {
    "joinpoint": {
      "id": "jp-smoke-messages",
      "level": 1,
      "name": "before_response",
      "host": "openclaw",
      "agent_session_id": "demo",
      "host_round_id": "run-1",
      "ts": "2026-05-15T12:00:00+00:00",
      "payload": {
        "messages": [
          { "role": "assistant", "content": "Earlier I mentioned rm -rf in an example." },
          { "role": "user", "content": "How do I list files in shell?" }
        ]
      }
    }
  }
}' | python3 -m json.tool
```

**Expected:** `user-shell-guard` appears in `injections` (user line matches `shell`).
The assistant line does **not** satisfy `user_message` even though `rm` appears in
the flattened `text` field.

**Counter-example:** repeat with only `joinpoints: ["before_response"]` on the same
concern — the assistant’s `rm -rf` in flattened history can activate the concern.

### 3. Live OpenClaw (verification checklist)

**Prerequisites**

- Daemon from repo / current `main` — `uv run opencoat runtime up` (not pip-only 0.1.3 without discovery; use **0.1.5+** on PyPI).
- Bridge installed and gateway restarted; log shows `[opencoat-bridge] registered`.
- Plugin config: `allowPromptInjection: true`, optional `logActivations: true`.
- Concern uses AOP (AspectJ) `user_message()` (see `[docs/guides/concern-authoring-aop.md](../../docs/guides/concern-authoring-aop.md)`) — upsert via `opencoat concern import` or `--demo`.

**Steps**

1. Import a message-level guard (example `user-shell-guard` from §2) or `opencoat concern import --demo`.
2. In Telegram/TUI, send: `How do I list files in shell safely?` — should weave on **user** line only.
3. In gateway logs, confirm `joinpoint.submit` / activation lines mention the concern id (when `logActivations` is on).
4. **DCN** — child joinpoint ids, not only manual curl ids:

```bash
curl -sS http://127.0.0.1:7878/rpc -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"dcn.activation_log","params":{"concern_id":"user-shell-guard","limit":5},"id":3}' \
  | python3 -m json.tool
```

**Pass criteria**


| Check                                                                     | Pass   |
| ------------------------------------------------------------------------- | ------ |
| `injections` non-empty on user shell question                             | `[ok]` |
| DCN `joinpoint_id` contains `#msg:` (e.g. `jp-oc-…#msg:1`)                | `[ok]` |
| Assistant-only `rm -rf` in history does **not** fire `user_message` guard | `[ok]` |
| `opencoat concern list` shows imported concern                            | `[ok]` |


Requires **JoinpointDiscovery** (`expand_prompt_surface` on by default). Older daemons ignore `messages[]` and only match lifecycle names.

## Reload after upgrade

```bash
cd /path/to/OpenCOAT/integrations/openclaw-opencoat-bridge
npm run build
openclaw gateway restart
grep opencoat-bridge ~/.openclaw/logs/gateway.log   # expect "registered 28 hooks" + runtime observers
```

## Weaving expectations

| Hook / joinpoint | Typical injections |
| --- | --- |
| `message_received` → `on_user_input` | Often **empty** if your concerns only list `before_response` / `user_message` |
| `before_prompt_build` → `before_response` | Main weave path when keywords match flattened prompt or discovered `user_message` rows |

For background DCN maintenance (decay, merge, conflict edges), run the daemon with
heartbeat enabled — see root [`README.md`](../../README.md) § Heartbeat + DCN maintenance (M6).

**Optional chat mining:** set `extractOnUserMessage: true` so the bridge passes
`extract_from_chat: true` on `joinpoint.submit` (requires a configured LLM on the
daemon). Extraction updates the concern store; it does not always add rows to
`injections` on that same submit.

## Limitations (v0.1 bridge)

- Prompt folding uses `prependSystemContext` only (not full dotted-path injector parity with Python `OpenClawInjector`).
- **`queue.before_enqueue`** sync veto/rewrite requires OpenClaw **fork** (`queue_before_enqueue` hook). Poll fallback in `runtime-observers.ts` is observe-only.
- Non-subagent **`task.before_create`** is observe-only (task poll); spawn veto works on `subagent_spawning` only.
- `reply_run.*` from agent events approximates `ReplyRunRegistry` phases; sub-second phase edges may be missed without native hooks.
- Double joinpoint fire (`on_user_input` + `before_response`) is intentional when concerns list both.
- Section discovery depends on hosts passing `sections` on message objects (uncommon today); message-level JPs always apply when `messages` is present.

Queue dogfood: [`examples/09_queue_hook_dogfood/README.md`](../../examples/09_queue_hook_dogfood/README.md).

See also: `[examples/04_openclaw_with_runtime/README.md](../../examples/04_openclaw_with_runtime/README.md)` (toy bus), `[docs/guides/concern-authoring-aop.md](../../docs/guides/concern-authoring-aop.md)`, and `[docs/design/v0.2-system-design.md](../../docs/design/v0.2-system-design.md)` §4.7.1.
