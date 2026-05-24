# ADR 0011 — OpenClaw joinpoint model v0.1

## Status

Accepted (design + catalog aliases on `main`; bridge **29** plugin hooks + runtime
observers; **`queue.before_enqueue` / `queue.after_enqueue` sync collaborative
guard on HyperdustLabs fork** — see [joinpoint model §4.1](../design/opencoat-openclaw-joinpoint-model-v0.1.md#41-mvp-emit-status-bridge-integrationsopenclaw-opencoat-bridge)). **In-proc authoritative `ReflexMonitor`** (fail-closed) is v0.3 / [ADR-0012](./0012-self-built-effector-control-plane.md), not this ADR.

## Context

OpenCOAT shipped a flat joinpoint catalog (38 names, 8 levels in
`opencoat_runtime_core/joinpoint/catalog.py`) and an OpenClaw gateway bridge
(**29** plugin hooks + runtime observers). OpenClaw’s real behavior control spans
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
   P3 bridge runtime observers → **P5a fork queue hooks**). **Collaborative → authoritative** staging: [v0.3 §10](../design/v0.3-morphogenetic-architecture.md#10-openclaw--效应器内核改造权威反射监视器), ADR-0012.

## Consequences

- `opencoat inspect joinpoints` lists legacy + v0.1 MVP names.
- Concerns may author `joinpoints: ["tool.before_call"]` or `["before_tool_call"]`.
- **Decision path (fork + collaborative bridge):** `queue.before_enqueue` sync
  **block** / prompt & summaryLine **rewrite** via `queue_before_enqueue` +
  bridge `queue_guard` (daemon RPC). Requires fork gateway — see joinpoint model §5.7.
- **Observe fallback:** queue depth poll still emits `queue.before_enqueue` /
  `queue.before_collect` when native hooks are absent (no veto).
- **Still observe-only or partial:** fine-grained `reply_run.phase.*`, generic
  non-subagent `task.before_create`, `tool.result.before_emit`, unified
  `memory.before_write` on every path.
- **ADR-0012** does not supersede this ADR for **unforked** hosts; cooperative
  bridge remains the integration path there.
- Future ADRs may supersede alias table when v0.1 names become canonical on the wire.

## References

- ADR-0003 (host adapter as plugin), ADR-0002 (AOP mechanism), ADR-0012 (effector / in-proc TCB)
- [v0.3 morphogenetic architecture §10](../design/v0.3-morphogenetic-architecture.md)
- [OpenClaw fork](https://github.com/HyperdustLabs/openclaw) — branch `opencoat/hooks-v0.1`
- [integrations/openclaw-opencoat-bridge/README.md](../../integrations/openclaw-opencoat-bridge/README.md)
