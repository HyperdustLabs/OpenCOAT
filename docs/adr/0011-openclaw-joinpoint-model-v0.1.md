# ADR 0011 — OpenClaw joinpoint model v0.1

## Status

Accepted (design + catalog aliases on `main`; bridge runtime observers for MVP
queue/reply_run/task observe paths; synchronous native hooks remain follow-up).

## Context

OpenCOAT shipped a flat joinpoint catalog (38 names, 8 levels in
`opencoat_runtime_core/joinpoint/catalog.py`) and an OpenClaw gateway bridge
(26 plugin hooks + runtime observers). OpenClaw’s real behavior control spans
`auto-reply/reply` (queue, `ReplyRunRegistry`, `agent-runner`),
`agents/pi-embedded-runner` (`onAgentEvent`), and `tasks/task-registry` —
not only prompt/tool hooks.

Authors need a stable naming scheme aligned with OpenClaw lifecycle nodes
without OpenCOAT mutating OpenClaw internal state (session store, queue maps,
task indexes).

## Decision

1. **Principle (SoC):** OpenClaw owns state; OpenCOAT owns concern; joinpoints
   connect them. Advice is `read_only` / `policy_only` / `host_api_only` —
   never direct writes to OpenClaw singletons.
2. **Naming:** Adopt dotted **domain.phase** names for OpenClaw alignment
   (e.g. `tool.before_call`, `queue.before_enqueue`). Legacy flat names
   (`before_tool_call`, `on_user_input`) remain **canonical** in the catalog
   for backward compatibility.
3. **Aliases:** `opencoat_runtime_core.joinpoint.aliases.OPENCLAW_V01_ALIASES`
   maps v0.1 names → canonical names. `PointcutMatcher` treats aliased names as
   equivalent (`joinpoint_names_match`).
4. **MVP wave:** Register 17 joinpoints from the design doc (§4) in the catalog;
   those without a legacy twin are new catalog entries until OpenClaw emits them.
5. **Host mapping:** Python `OPENCLAW_EVENT_MAP` and the TS bridge keep legacy
   names on the wire for now; adapters may set `JoinpointEvent.name` to either
   form. Pointcuts may use either form.
6. **Full model:** Documented in
   [`docs/design/opencoat-openclaw-joinpoint-model-v0.1.md`](../design/opencoat-openclaw-joinpoint-model-v0.1.md)
   (14 domains; **§5 A/B/C availability tiers** for OpenClaw vs catalog). Implementation is phased (P0 catalog aliases → P2 plugin hooks →
   P3 bridge runtime observers for observe-only MVP emits).

## Consequences

- `opencoat inspect joinpoints` lists legacy + v0.1 MVP names.
- Concerns may author `joinpoints: ["tool.before_call"]` or `["before_tool_call"]`.
- Queue / reply-run / task joinpoints are **emitted observe-only** by the bridge
  (`onAgentEvent`, queue-depth poll, `runtime.tasks` poll) — not synchronous veto
  at `enqueueFollowupRun` / `createTaskRecord` without upstream plugin hooks.
- Future ADRs may supersede alias table when v0.1 names become canonical on the wire.

## References

- ADR-0003 (host adapter as plugin), ADR-0002 (AOP mechanism)
- [OpenClaw repo](https://github.com/openclaw/openclaw) — `src/auto-reply/reply/`, `src/tasks/`
- [integrations/openclaw-opencoat-bridge/README.md](../../integrations/openclaw-opencoat-bridge/README.md)
