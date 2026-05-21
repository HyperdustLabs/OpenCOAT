# OpenCOAT × OpenClaw Joinpoint Model v0.1

**Status:** accepted — [ADR-0011](../adr/0011-openclaw-joinpoint-model-v0.1.md)  
**Implementation:** `joinpoint/catalog.py`, `joinpoint/aliases.py`, `PointcutMatcher` alias equivalence; bridge `hook-bindings.ts` + `runtime-observers.ts`  
**Related:** [v0.2 system design](./v0.2-system-design.md) §2.2, [ADR-0002 AOP](../adr/0002-aop-as-mechanism.md), [OpenClaw bridge README](../../integrations/openclaw-opencoat-bridge/README.md)

---

## Core principle

> **Joinpoints are where OpenCOAT can observe, match, inject, and verify — not where OpenCOAT directly mutates OpenClaw internal state.**

```text
OpenClaw owns state.
OpenCOAT owns concern.
Joinpoint connects them.
```

Host Adapter maps host events → `JoinpointEvent`; COT Runtime runs extract → match → vector → advice → weave → verify → lifecycle (see v0.2 §2.2).

**Mutation boundary:** advice may return `tool_guard`, `prependSystemContext`, queue/run *policy suggestions*, etc. OpenClaw (or its plugin host) applies them via public APIs. OpenCOAT must not write `activeRunsByKey`, `queue.items`, `tasks` Map, or session store internals.

---

## 1. Layering (14 domains)

| Level | Domain | OpenClaw anchor (examples) |
| --- | --- | --- |
| 0 | Runtime | gateway start/stop, config reload, daemon tick |
| 1 | Session / Run | `ReplyRunRegistry`, `ReplyOperation` phases |
| 2 | Input / Admission | channel ingress, session/agent resolution |
| 3 | Queue | `FollowupRun`, `enqueueFollowupRun`, `scheduleFollowupDrain` |
| 4 | Prompt / Context | `before_prompt_build`, COPR, compaction |
| 5 | Reasoning / Planning | `onAgentEvent` plan stream |
| 6 | Tool / Approval / Command | `before_tool_call`, approval, command_output, patch |
| 7 | Memory / Session state | session store, transcript, compaction |
| 8 | Task / Flow | `TaskRegistry`, `createTaskRecord`, TaskFlow |
| 9 | Output / Delivery | streaming, channel deliver, silent reply |
| 10 | Verification / Feedback | verifier, concern reinforce/weaken |
| 11 | Heartbeat / Background | heartbeat, cron fire, system events |
| 12 | Error / Recovery | fallback, retry, overflow, drain |
| 13 | Fine-grained structure | span, token, field path, thought unit |

---

## 2. Joinpoint names by domain

Naming: `domain.object.phase` (optional `path` for structure).  
Phases: `before` | `on` | `after` | `error` | `terminal`.

### Level 0 — Runtime

```text
runtime.start
runtime.ready
runtime.tick
runtime.reload
runtime.shutdown
runtime.error
runtime.recovery
runtime.config_loaded
runtime.config_changed
```

### Level 1 — Session / Run (`reply_run.*`)

Maps OpenClaw `ReplyOperation` phases: `queued`, `preflight_compacting`, `memory_flushing`, `running`, `completed`, `failed`, `aborted`.

```text
reply_run.before_begin
reply_run.after_begin
reply_run.phase.queued
reply_run.phase.preflight_compacting
reply_run.phase.memory_flushing
reply_run.phase.running
reply_run.before_attach_backend
reply_run.after_attach_backend
reply_run.before_complete
reply_run.after_complete
reply_run.before_fail
reply_run.after_fail
reply_run.before_abort_by_user
reply_run.after_abort_by_user
reply_run.before_abort_for_restart
reply_run.after_abort_for_restart
reply_run.idle
```

### Level 2 — Input / Admission

```text
input.received
input.normalized
input.auth_checked
input.route_resolved
input.session_resolved
input.agent_resolved
input.before_admission
input.after_admission
input.rejected
```

### Level 3 — Queue

Modes: `steer` | `followup` | `collect` | `interrupt`. Drop: `old` | `new` | `summarize`.

```text
queue.before_enqueue
queue.after_enqueue
queue.dedupe_check
queue.drop_policy_select
queue.before_drop
queue.after_drop
queue.before_collect
queue.after_collect
queue.before_summarize
queue.after_summarize
queue.before_interrupt
queue.after_interrupt
queue.before_drain
queue.after_drain
queue.item_aborted
queue.cross_channel_detected
queue.authorization_group_split
```

### Level 4 — Prompt / Context

Aligns with COPR + existing `prompt_section` catalog paths.

```text
prompt.before_build
prompt.after_build
prompt.system.role_definition
prompt.system.rules
prompt.developer.constraints
prompt.user.original_request
prompt.runtime.active_concerns
prompt.runtime.tool_instructions
prompt.runtime.memory_context
prompt.runtime.output_format
prompt.runtime.verification_rules
prompt.before_send_to_model
context.before_injection
context.after_injection
context.before_compaction
context.after_compaction
```

Discovery children (unchanged conceptually): `user_message`, `assistant_message`, … as `#msg:N` under a coarse parent.

### Level 5 — Reasoning / Planning

Thought-unit JPs apply only to **host-visible** objects (plan steps, hypotheses), not hidden chain-of-thought.

```text
reasoning.before_start
reasoning.after_start
reasoning.before_step
reasoning.after_step
planning.before_start
planning.after_start
planning.plan_created
planning.plan_updated
planning.step_created
planning.step_selected
planning.step_completed
planning.step_failed
decision.before_select
decision.after_select
```

### Level 6 — Tool / Approval / Command

```text
tool.before_select
tool.after_select
tool.before_call
tool.arguments.before_validate
tool.arguments.after_validate
tool.before_execute
tool.after_execute
tool.result.received
tool.result.before_emit
tool.result.after_emit
approval.before_request
approval.requested
approval.granted
approval.denied
command.before_execute
command.output_stream
command.after_execute
patch.before_apply
patch.after_apply
patch.summary_created
```

Primary weave path for guards: `tool.before_call` → `tool_guard` advice → host returns allow / block / rewrite.

### Level 7 — Memory / Session state

```text
memory.before_read
memory.after_read
memory.before_write
memory.after_write
memory.before_update
memory.after_update
memory.before_delete
memory.after_delete
session.before_load
session.after_load
session.before_update
session.after_update
session.before_compaction
session.after_compaction
session.context_overflow_detected
session.model_fallback_selected
session.usage_recorded
```

### Level 8 — Task / Flow

```text
task.before_create
task.after_create
task.before_merge_existing
task.after_merge_existing
task.before_link_flow
task.after_link_flow
task.before_start
task.after_start
task.progress_recorded
task.before_terminal
task.after_terminal
task.before_cancel
task.after_cancel
task.before_lost
task.after_lost
task.before_delete
task.after_delete
flow.before_sync_from_task
flow.after_sync_from_task
flow.before_cancel
flow.after_cancel
flow.terminal
```

### Level 9 — Output / Delivery

```text
response.before_draft
response.draft_created
response.before_stream
response.streaming_delta
response.after_stream
response.before_final
response.after_final
response.before_delivery
response.after_delivery
response.delivery_failed
response.silent_reply_detected
response.block_reply_flush
```

### Level 10 — Verification / Feedback

```text
verification.before_start
verification.claim_extracted
verification.risk_checked
verification.format_checked
verification.tool_result_checked
verification.memory_write_checked
verification.after_pass
verification.after_fail
feedback.received
feedback.before_apply
feedback.after_apply
concern.before_reinforce
concern.after_reinforce
concern.before_weaken
concern.after_weaken
```

### Level 11 — Heartbeat / Background

```text
heartbeat.before_request
heartbeat.requested
heartbeat.before_run
heartbeat.after_run
heartbeat.ack_received
heartbeat.noop
background_task.created
background_task.updated
background_task.completed
cron.before_fire
cron.after_fire
system_event.enqueued
system_event.delivered
```

OpenCOAT daemon `runtime_tick` (DCN maintenance) is **OpenCOAT-side**; map to `runtime.tick` with `source: opencoat`, not OpenClaw heartbeat.

### Level 12 — Error / Recovery

```text
error.detected
error.classified
error.before_recovery
error.after_recovery
fallback.before_select
fallback.after_select
retry.before
retry.after
timeout.detected
context_overflow.detected
compaction_failure.detected
gateway_draining.detected
command_lane_cleared
```

### Level 13 — Fine-grained structure

**Spans:** `span.claim`, `span.instruction`, `span.constraint`, `span.question`, `span.preference`, `span.high_risk_instruction`, `span.tool_argument_description`, `span.code_block`, `span.json_field`

**Tokens:** `token.must`, `token.never`, `token.guaranteed`, `token.all_in`, `token.ignore_previous_rules`, `token.do_not_tell_user`, `token.secret`, `token.private_key`

**Fields:** `tool_call.arguments.*`, `memory_write.*`, `response.json.*`, `code.symbol.*`, `task.record.*`

**Thought units:** `plan_step`, `hypothesis`, `candidate_answer`, `decision_option`, `verification_claim`, `tool_selection_reason`, `risk_assessment`

---

## 3. Advice types per domain (summary)

| Domain | Typical advice |
| --- | --- |
| Prompt / Context | `reasoning_guidance`, `response_requirement`, `verification_rule` |
| Queue | queue policy / collect / interrupt / summarize *suggestions* (host executes) |
| Tool | `tool_guard`, argument guard, block / require_approval / rewrite |
| Task / Flow | task metadata, split, cancel, terminal verification |
| Response | `rewrite_guidance`, format / citation / risk checks |
| Verification | verifier rules, retry, concern lifecycle |
| Heartbeat | proactive check, DCN maintenance hints |

---

## 4. MVP subset (17 joinpoints)

First integration wave — enough for input → queue → run → prompt → tool → task → response → verify → lifecycle:

```text
input.received
queue.before_enqueue
queue.before_collect
reply_run.before_begin
reply_run.phase.running
prompt.before_send_to_model
planning.plan_updated
tool.before_call
tool.result.received
approval.requested
task.before_create
task.after_create
task.before_terminal
response.before_final
verification.after_fail
heartbeat.before_run
error.detected
```

### 4.1 MVP emit status (bridge `integrations/openclaw-opencoat-bridge`)

| MVP joinpoint | Emitted today | Bridge source | Sync veto at host call site |
| --- | --- | --- | --- |
| `input.received` | yes | `message_received`, `inbound_claim`, `before_dispatch` | no (observe / buffer) |
| `queue.before_enqueue` | yes | **`queue_before_enqueue` plugin hook** (fork); queue depth poll fallback | **yes** — `block` / `queue.prompt` / `queue.summary_line` rewrite via bridge `queue_guard` |
| `queue.after_enqueue` | yes (observe) | **`queue_after_enqueue` plugin hook** (fork); poll snapshot sync | no |
| `queue.before_collect` | yes (observe) | queue depth poll (depth decrease) | no |
| `reply_run.before_begin` | yes (observe) | `onAgentEvent` lifecycle `start` | no |
| `reply_run.phase.running` | yes (observe) | first `assistant` / `tool` / `item` after start | no |
| `prompt.before_send_to_model` | yes | `before_prompt_build`, `message_sending`, … | partial (`prependSystemContext`, cancel) |
| `planning.plan_updated` | yes (observe) | `onAgentEvent` `plan` stream | no |
| `tool.before_call` | yes | `before_tool_call` | yes (`block` / param guard) |
| `tool.result.received` | yes (observe) | `after_tool_call` | no |
| `approval.requested` | yes (observe) | `onAgentEvent` `approval` stream | no |
| `task.before_create` | yes (observe) | `subagent_spawning` + task poll (first sight) | spawn veto only on subagent hook |
| `task.after_create` | yes (observe) | subagent hooks + task poll | no |
| `task.before_terminal` | yes (observe) | `subagent_ended` + task poll | no |
| `response.before_final` | partial | `message_sending` cancel path | cancel outbound only |
| `verification.after_fail` | no | — | — |
| `heartbeat.before_run` | no | OpenCOAT `runtime_tick` / future hook | — |
| `error.detected` | yes (observe) | `onAgentEvent` lifecycle `error` | no |

Default: `runtimeObservers: true`, `observerPollMs: 500`. Full hook table: [bridge README](../../integrations/openclaw-opencoat-bridge/README.md).

---

## 5. OpenClaw availability tiers (A / B / C)

Many catalog joinpoints are **OpenCOAT cut points** — valid for pointcuts and DCN — that OpenClaw does **not** yet expose as synchronous host hooks. Classify every integration path as:

```text
A. Usable now     — OpenClaw event, plugin hook, or stable runtime API the bridge can call
B. Wrapper tier   — wrap a public function or adapter boundary without mutating internal Maps
C. Not direct     — needs OpenClaw middleware/hook PR, or is OpenCOAT-internal (COPR / span / token)
```

### 5.1 One-line conclusion

**Best signals today:** plugin hooks (`before_prompt_build`, `before_tool_call`, …), **`api.runtime.events.onAgentEvent`** (`plan`, `tool`, `item`, `approval`, `command_output`, `patch`, `compaction`, `lifecycle`), task registry APIs, queue depth / followup run observability.

**Weakest / internal-only:** `token.*`, `span.*`, `prompt.section.*` (until host passes structured sections), implicit planner steps, true memory read/write on every path, unified `response.before_final` verifier (partial via `message_sending` only).

**Strong control gap (upstream):** full `reply_run.phase.*`, `tool.result.before_emit`, unified `memory.before_write`, and paths where only post-hoc agent events exist today. **`queue.before_enqueue` sync veto shipped on OpenClaw fork** (`queue_before_enqueue` hook + bridge `queue_guard`); poll remains observe-only fallback.

### 5.2 Tier A — usable now

| Surface | OpenClaw anchor | v0.1 / legacy JP | Bridge today | Control |
| --- | --- | --- | --- | --- |
| Plugin hooks | `before_prompt_build`, `llm_*`, `agent_end` | `before_response`, reasoning JPs | yes | **weave** (`prependSystemContext`) |
| Plugin hooks | `before_tool_call` | `tool.before_call` | yes | **block** / param guard |
| Plugin hooks | `message_sending` | `before_response` | yes | **cancel** outbound |
| Plugin hooks | `subagent_spawning` | `task.before_create` | yes | spawn **veto** |
| Plugin hooks | `before_compaction` / `after_compaction` | memory JPs | yes | observe (+ same boundary as internal compact hook) |
| Agent event stream | `stream: plan` | `planning.plan_updated` | observer | observe |
| Agent event stream | `stream: approval` (phase requested) | `approval.requested` | observer | observe |
| Agent event stream | `stream: compaction` start/end | memory JPs | observer | observe |
| Agent event stream | `stream: lifecycle` start | `reply_run.before_begin` | observer | observe |
| Agent event stream | `stream: tool` / `item` / `assistant` after start | `reply_run.phase.running` | observer | observe |
| Agent event stream | `stream: command_output` | `command.output_stream` | yes (observe) | no |
| Agent event stream | `stream: patch` | `patch.summary_created` | yes (observe) | no |
| Task API | `runtime.tasks.runs.bindSession().list()` | `task.*` | poll diff | observe |
| Task hooks | `subagent_*` | `task.after_create`, `task.before_terminal` | yes | observe / spawn veto |
| Input | `message_received`, `inbound_claim`, `before_dispatch` | `input.received` | yes | observe / extract |
| Plugin hooks | `queue_before_enqueue` / `queue_after_enqueue` | `queue.before_enqueue` / `queue.after_enqueue` | yes (fork) | **block** / prompt & summaryLine **rewrite** |
| Queue poll | `getFollowupQueueDepth` | `queue.before_enqueue`, `queue.before_collect` | fallback | observe only (no veto) |

**Important correction:** OpenClaw’s plugin hook `before_tool_call` **is** a pre-execute guard — do not confuse it with `onAgentEvent` `stream: tool`, which fires around tool **start** and is observe-only. Catalog name `tool.before_call` maps to the plugin hook, not `tool.started`.

### 5.3 Tier B — wrapper or weak modulation

| Joinpoint (design) | How to attach | Bridge / OpenCOAT today |
| --- | --- | --- |
| `queue.before_drain` | wrap `scheduleFollowupDrain` | not wired |
| `input.before_enqueue` | adapter before enqueue | partial (`on_user_input` buffer) |
| `prompt.before_send_to_model` | `FollowupRun.extraSystemPrompt`, hook fold | plugin + discovery |
| `model.before_select` | wrap `runAgentTurnWithFallback` | not wired |
| `reply_run.phase.*` (fine phases) | wrap `ReplyOperation.setPhase` | approximated via lifecycle only |
| `response.streaming_delta` | `onPartialReply` / block reply callbacks | not wired |
| `system_event.enqueued` | wrap `enqueueSystemEvent` | not wired |

OpenCOAT applies **weak modulation** here: extra system prompt, queue/task *policy suggestions* in submit results (host must apply), timeouts, tool visibility — not direct Map mutation.

### 5.4 Tier C — native hook or OpenCOAT-internal

**Needs OpenClaw PR (middleware at call site):**

```text
tool.before_execute          # if stricter than plugin before_tool_call (args rewrite mid-flight)
reply_run.phase.*            # per-phase hooks on ReplyOperation
memory.before_read / before_write   # unified memory middleware (compaction hooks are partial)
response.before_final        # unified verifier before channel delivery (message_sending is partial)
response.before_delivery
plan_step.before_execute / decision.before_select
```

**OpenCOAT-internal (not OpenClaw hooks):** parse host payload → COPR / prompt tree → child joinpoints:

```text
token.*  span.*  prompt.section.*  user_message#msg:N  runtime_prompt.*
```

Requires `messages[]` / `sections[]` on submit (bridge sends `messages[]` on `before_prompt_build`; JoinpointDiscovery expands).

### 5.5 Observation vs strong control

```text
Observation (DCN, audit, meta-review):
  plan / approval / patch / command_output / compaction events
  queue depth diff, task registry diff, reply_run lifecycle approx

Strong control (host must apply advice):
  before_prompt_build → prependSystemContext
  before_tool_call    → block / params
  message_sending     → cancel
  subagent_spawning   → error status

Upstream “neurosurgery” (recommended order):
  1. tool.before_execute middleware (if plugin hook insufficient)
  2. response.before_final verifier hook
  3. memory.before_write middleware (beyond compaction)
```

### 5.6 MVP integration waves

| Wave | Joinpoints | Mechanism |
| --- | --- | --- |
| **Shipped (bridge)** | §4.1 MVP rows marked “yes” | plugin hooks + `runtime-observers.ts` |
| **Shipped (observe)** | `command.output_stream`, `patch.summary_created`, `error.detected` | `onAgentEvent` mapping in bridge `runtime-observers.ts` |
| **Next (observe)** | streaming deltas | extend `onAgentEvent` / outbound callbacks |
| **Shipped (fork + bridge)** | `queue.before_enqueue` / `queue.after_enqueue` sync veto + observe | OpenClaw `queue_before_enqueue` / `queue_after_enqueue` + bridge `queue_guard` |
| **Next (upstream)** | `reply_run.phase.*`, `response.before_final`, `tool.result.before_emit` | OpenClaw plugin hooks at call sites |
| **OpenCOAT-only** | `span.*`, `token.*`, message children | discovery on prompt payload |

Design catalog lists **17 MVP names**; bridge **strong loop** today: input → prompt fold → tool guard → optional outbound cancel → **queue enqueue veto/rewrite (fork)** → task/subagent edges, plus observe-only run/task/event stream for DCN. Dogfood: [`examples/09_queue_hook_dogfood`](../../examples/09_queue_hook_dogfood/README.md).

---

## 6. Joinpoint map (tree)

```text
OpenCOAT Joinpoint (v0.1)
├── Runtime
│   ├── runtime.start / runtime.tick / runtime.error / runtime.recovery
├── Session / Run
│   ├── reply_run.before_begin / reply_run.phase.* / reply_run.before_abort
├── Input / Admission
│   ├── input.received … input.after_admission
├── Queue
│   ├── queue.before_enqueue / queue.before_collect / queue.before_drain
├── Prompt / Context
│   ├── prompt.before_build / prompt.runtime.* / context.before_compaction
├── Reasoning / Planning
│   ├── planning.plan_updated / decision.before_select
├── Tool / Approval / Command
│   ├── tool.before_call / approval.requested / patch.before_apply
├── Memory / Session
│   ├── memory.before_write / session.before_compaction
├── Task / Flow
│   ├── task.before_create / task.before_terminal / flow.after_sync_from_task
├── Output / Delivery
│   ├── response.before_final / response.before_delivery
├── Verification / Feedback
│   ├── verification.after_fail / feedback.received
├── Heartbeat / Background
│   ├── heartbeat.before_run / cron.before_fire
├── Error / Recovery
│   ├── error.detected / fallback.before_select
└── Fine-grained Structure
    ├── span.* / token.* / tool_call.arguments.* / task.record.*
```

---

## 7. Wire shape (reference)

v0.1 extends `JoinpointEvent` with domain metadata; `name` remains the pointcut key (flat or dotted).

```typescript
type OpenCOATJoinpointMeta = {
  id: string
  source: "openclaw" | "opencoat" | "custom"
  domain:
    | "runtime" | "session" | "run" | "input" | "queue" | "prompt"
    | "reasoning" | "planning" | "tool" | "approval" | "command"
    | "memory" | "task" | "flow" | "response" | "verification"
    | "heartbeat" | "error" | "structure"
  name: string
  phase?: "before" | "on" | "after" | "error" | "terminal"
  sessionKey?: string
  runId?: string
  taskId?: string
  flowId?: string
  agentId?: string
  messageId?: string
  path?: string
  hostStateSnapshot?: unknown  // read-only
  mutationBoundary: "read_only" | "policy_only" | "host_api_only"
  createdAt: number
}
```

Example pointcut target:

```json
{
  "joinpoint": "tool.before_call",
  "path": "tool_call.arguments.command",
  "source": "openclaw",
  "mutationBoundary": "policy_only"
}
```

---

## Appendix A — Built-in catalog today (`opencoat inspect joinpoints`)

**38 names**, **8 levels** (protocol `JoinpointLevel`). Levels `structure_field` and `thought_unit` exist in enum but have **no catalog entries yet**.

| Level | Count | Names |
| --- | ---: | --- |
| runtime | 5 | `runtime_start`, `runtime_stop`, `runtime_tick`, `runtime_error`, `runtime_recovery` |
| lifecycle | 15 | `on_user_input`, `before_reasoning`, `after_reasoning`, `before_planning`, `after_planning`, `before_tool_call`, `after_tool_call`, `before_response`, `after_response`, `before_memory_write`, `after_memory_write`, `on_error`, `on_feedback`, `on_heartbeat`, `adviceexecution` |
| message | 7 | `system_message`, `developer_message`, `user_message`, `assistant_message`, `tool_message`, `memory_message`, `retrieved_context` |
| prompt_section | 9 | `system_prompt.*`, `developer_prompt.*`, `user_prompt.*`, `runtime_prompt.*` (see catalog.py) |
| span | 1 | `semantic_span` |
| token | 1 | `token` |

**Dynamic children:** `JoinpointDiscovery` adds `#msg:N`, `#sec:…` under a parent submit.

### A.1 Legacy name → v0.1 (normative mapping)

| Legacy (shipped catalog) | v0.1 primary | Notes |
| --- | --- | --- |
| `runtime_start` | `runtime.start` | bridge: `session_start` |
| `runtime_stop` | `runtime.shutdown` | |
| `runtime_tick` | `runtime.tick` | OpenCOAT daemon heartbeat |
| `runtime_error` | `runtime.error` | |
| `runtime_recovery` | `runtime.recovery` | |
| `on_user_input` | `input.received` | bridge: `message_received` |
| `before_reasoning` | `reasoning.before_start` | design: `agent.before_llm_call` |
| `after_reasoning` | `reasoning.after_start` | |
| `before_planning` | `planning.before_start` | |
| `after_planning` | `planning.after_start` | |
| `before_tool_call` | `tool.before_call` | bridge: `before_tool_call` |
| `after_tool_call` | `tool.after_execute` | |
| `before_response` | `prompt.before_build` | bridge: `before_prompt_build` |
| `after_response` | `response.after_final` | |
| `before_memory_write` | `memory.before_write` | |
| `after_memory_write` | `memory.after_write` | |
| `on_error` | `error.detected` | |
| `on_feedback` | `feedback.received` | |
| `on_heartbeat` | `heartbeat.before_run` | OpenClaw heartbeat turn |
| `adviceexecution` | `concern.after_reinforce` | meta |
| `user_message` | `prompt.user.original_request` + child `#msg:N` | discovery |
| `system_message` | `prompt.system.role_definition` (child) | |
| `runtime_prompt.active_concerns` | `prompt.runtime.active_concerns` | 1:1 path |
| `semantic_span` | `span.*` | |
| `token` | `token.*` | |

New v0.1-only names (no legacy alias): all `queue.*`, `reply_run.*`, `task.*`, `flow.*`, `approval.*`, most `session.*`.

**Compatibility:** pointcuts may use legacy flat names until catalog registers dotted aliases (dual match).

---

## Appendix B — OpenClaw → v0.1 (integration)

### B.1 Gateway plugin hooks (`api.on`, 26/29)

Canonical table lives in [bridge README § Hook → joinpoint mapping](../../integrations/openclaw-opencoat-bridge/README.md). Summary:

| Kind | Hooks (examples) | Legacy JP | Effect |
| --- | --- | --- | --- |
| Weave | `before_prompt_build` | `before_response` | `prependSystemContext` |
| Guard | `before_tool_call` | `before_tool_call` | `block` / params |
| Outbound | `message_sending` | `before_response` | `cancel` |
| Task | `subagent_spawning` … `subagent_ended` | `task.*` | spawn veto + observe |
| Observe | `session_*`, `gateway_*`, `llm_*`, compaction, … | various | submit only |

Skipped (sync hot path): `before_message_write`, `tool_result_persist`. Skipped (install): `before_install`.

### B.2 Runtime observers (not `api.on`)

Bridge module `runtime-observers.ts` — uses host APIs already available to plugins:

| Source | Joinpoints | Mechanism |
| --- | --- | --- |
| `api.runtime.events.onAgentEvent` | `reply_run.before_begin`, `reply_run.phase.running`, `planning.plan_updated`, `approval.requested`, `command.output_stream`, `patch.summary_created`, `error.detected` (lifecycle `error`), compaction → `before_memory_write` / `after_memory_write` | event stream |
| `api.registerHook` | `session:compact:before` / `after` → memory JPs | internal gateway hooks |
| Host `getFollowupQueueDepth` | `queue.before_enqueue`, `queue.before_collect` | `registerService` poll per tracked `sessionKey` |
| `api.runtime.tasks.runs.bindSession().list()` | `task.before_create`, `task.after_create`, `task.before_terminal` | task registry diff poll |

**Tracked sessions:** any hook `ctx.sessionKey` and agent events with `sessionKey`.

**Limits:** observe-only at poll/event granularity; does not replace native hooks at `enqueueFollowupRun`, `ReplyRunRegistry` phase edges, or `createTaskRecord` for synchronous policy veto.

### B.3 Python host event map (design, not in TS bridge)

| OpenClaw event | Legacy | v0.1 |
| --- | --- | --- |
| `agent.started` | `runtime_start` | `runtime.start` |
| `agent.user_message` | `on_user_input` | `input.received` |
| `agent.before_llm_call` | `before_reasoning` | `reasoning.before_start` |
| `agent.after_llm_call` | `after_reasoning` | `reasoning.after_start` |
| `agent.before_tool` | `before_tool_call` | `tool.before_call` |
| `agent.after_tool` | `after_tool_call` | `tool.after_execute` |
| `agent.before_response` | `before_response` | `prompt.before_build` |
| `agent.after_response` | `after_response` | `response.after_final` |
| `agent.memory_write` | `before_memory_write` | `memory.before_write` |
| `agent.error` | `on_error` | `error.detected` |

### B.4 OpenClaw internal — native hook still needed for sync control

| OpenClaw module | v0.1 emit | Bridge today | Native hook for veto |
| --- | --- | --- | --- |
| `auto-reply/reply/queue.ts` | `queue.*` | depth poll → before_enqueue / before_collect | yes — enqueue/collect call sites |
| `auto-reply/reply/reply-run-registry.ts` | `reply_run.*` phases | lifecycle + running approx | yes — per-phase hooks |
| `auto-reply/reply/agent-runner.ts` | `prompt.before_send_to_model` | plugin hooks | partial |
| `agents/pi-embedded-runner` | `planning.*`, `patch.*`, … | `onAgentEvent` observe | optional |
| `tasks/task-registry.ts` | `task.*`, `flow.*` | task poll + subagent hooks | yes — `createTaskRecord` |
| cron / heartbeat | `heartbeat.before_run` | not wired | yes |

Repo: [github.com/openclaw/openclaw](https://github.com/openclaw/openclaw) — `src/auto-reply/reply/`, `src/agents/`, `src/tasks/`.

---

## Appendix C — Implementation phases

| Phase | Scope | Repo touch |
| --- | --- | --- |
| **P0** (done) | Legacy 38 + MVP 17 catalog + alias matching + ADR-0011 | `catalog.py`, `aliases.py`, matcher |
| **P1** (done) | Bridge docs + concern AOP examples | bridge README, authoring guide |
| **P2** (done) | 26 plugin hooks + weave/guard paths | `hook-bindings.ts`, bridge |
| **P3** (done, observe) | `queue.*`, `reply_run.*`, plan/approval via runtime observers | `runtime-observers.ts` |
| **P4** (partial) | `task.*` poll + subagent hooks; `flow.*` TBD | bridge; optional daemon mirror |
| **P5** | Sync native hooks at queue/run/task call sites | OpenClaw upstream PR |

---

## Summary

> OpenCOAT joinpoints are a **cognitive cut network** over OpenClaw’s lifecycle — not prompt injection points alone.

```text
OpenClaw provides behavior lifecycle.
OpenCOAT maps lifecycle nodes to joinpoints.
DCN activates concerns at joinpoints.
Advice modulates policy, prompt, tools, tasks, and verification.
OpenClaw retains final state mutation.
```
