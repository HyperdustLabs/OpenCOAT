# ADR 0012 — Self-built effector & deterministic control plane (OpenClaw fork)

## Status

Proposed (design). For the **deterministic** subset of joinpoints this supersedes
ADR-0011's "OpenClaw owns state; OpenCOAT owns concern" guest-plugin posture.
ADR-0011's cooperative bridge remains the integration path for **unforked** hosts.

## Context

- ADR-0002 made AOP the activation mechanism; ADR-0003 made the host adapter a
  plugin; ADR-0011 mapped OpenClaw's lifecycle into a 14-domain joinpoint model.
- The current OpenClaw integration is a **guest plugin**
  (`integrations/openclaw-opencoat-bridge`). Its enforcement is *cooperative*:
  the core emits `WeavingOperation` rows (`block`, `rewrite`, `suppress`, …);
  the bridge folds them into host decisions (`guardToolCall`,
  `messageSendingDecision`, `subagentSpawnDecision`, `queueBeforeEnqueueDecision`);
  OpenClaw applies them through public hooks and **retains final state mutation**
  (mutation boundary `read_only` / `policy_only` / `host_api_only`).
- Joinpoint model §5 classifies availability A/B/C. The genuinely deterministic
  interception points — `tool.before_execute` (mid-flight arg rewrite),
  `response.before_final` (verifier before delivery), `memory.before_write` — are
  **Tier C** for *in-proc authority*: blocked until `ReflexMonitor` lands in the fork.
  **`queue.before_enqueue` is Tier A on the fork** (native `queue_before_enqueue` hook)
  and already emits a **collaborative** `queue_guard` via the bridge — block/rewrite,
  not observe-only. Tier C still includes `memory.before_write`, `tool.result.before_emit`,
  and other sync paths skipped in the bridge. Even Tier A "strong control" today is
  cooperative: tool-arg rewrite is explicitly disabled in `injector.ts`
  ("Notes only — do not overwrite structured params on append advice").
- `WeavingOperation` (12 ops: `INSERT, REPLACE, SUPPRESS, ANNOTATE, WARN, VERIFY,
  REWRITE, DEFER, ESCALATE, BLOCK, COMPRESS`) is **undifferentiated** — it carries
  no hard/soft distinction and no fail-closed semantics. The 2004 paper's
  separation of a deterministic **Reflex layer (RAL ≈ spinal cord)** from the
  adaptive **Knowledge-Based layer (KBAL ≈ cortex)** is collapsed into one enum.
- Net: against a *stochastic LLM effector* behind a *cooperative host*, most
  weaving degrades to prompt text whose causal effect on behavior is unknowable.
  This is both a reliability gap and — per the morphogenetic design §9 — a
  **credit-assignment** gap for the aspect-net (you cannot cleanly credit an
  advice whose effect you cannot deterministically observe).

## Decision

1. **Build a first-party effector by forking OpenClaw.** The effector is a full
   MAN instance (`M = (N, ⇩_fast, ⇩_slow, F, κ, T)`) whose `EffectorKernel`
   owns the turn loop: route → `ExcitatoryNeuron.propose` → `InhibitoryReflex.mediate`
   → verify→repair → action execution → deterministic `r_t` emission.
   This is a new host class (`opencoat_runtime_host_effector`), not a guest plugin.
   Engineering landing: v0.3 architecture §3.5 + §10.

2. **Introduce typed aspect cell kinds** — not two separate "planes" but two cell
   types within the same connectome (`N`), unified under one plasticity law:
   - **`InhibitoryReflex`** (`A_reflex ⊆ A`). Deterministic, fail-closed, in-proc
     `ReflexMonitor` (small trusted core / TCB) at effect boundaries. Decisions are
     `Allow | Deny(reason) | Rewrite(action')` — **enforced, not suggested**.
     Safety-critical policies: `deny` on miss or error (fail-closed).
     `A_reflex` excluded from `⇩_slow` structural rewriting (conserved core /
     brainstem invariant). Engineering landing: v0.3 §3.3 + §10.2–10.3.
   - **`ExcitatoryNeuron`** (`A_cortex = A \ A_reflex`). Aspect-LLM neurons that
     `propose` candidates; weaver composes their advice into prompt injections.
     Subject to `⇩_slow` (morphogenesis). Engineering landing: v0.3 §3.2.

3. **Promote Tier C joinpoints to in-proc synchronous interception** in the fork
   via `ReflexMonitor.mediate`. OpenClaw hook mapping (v0.3 §10.1):

   | Hook | Gate | **Current (2026-05)** |
   |---|---|---|
   | `before_tool_call` | authority reflex (step 1) | collaborative — daemon RPC `tool_guard` |
   | `message_sending` | authority reflex (step 1) | collaborative — outbound cancel |
   | `subagent_spawning` | authority reflex (step 1) | collaborative — spawn veto |
   | `queue_before_enqueue` | authority reflex (step 1) | **collaborative on fork** — `queue_guard` block/rewrite |
   | `before_agent_reply` | verify→repair (step 2) | not wired (bridge uses `message_sending`) |
   | `after_tool_call` / `llm_output` / `agent_end` | `r_t` emission (step 3) | observe only — **`r_t` pending** |
   | `before_message_write` / `tool_result_persist` | re-admit when in-proc | **skipped** in bridge |

   Previously-skipped hooks (`before_message_write`, `tool_result_persist`) can be
   re-admitted because the monitor runs in-proc synchronously (no daemon RPC).

4. **Tag the substrate.** Annotate each `WeavingOperation` / `AdviceType` with
   `enforcement: hard | soft`, `fail_mode`, and add `neuron_type: excitatory |
   inhibitory` to `Concern`. Designate the conserved core `A_reflex` via a
   `reflex: true` marker excluded from `PlasticityEngine` rewrites.

5. **Wire the closed loop: `r_t` → `CreditField` → `PlasticityEngine`.** Hard
   decisions produce clean credit (causal effect known); soft advice credit is
   statistically estimated. The plasticity engine runs at three time scales (fast /
   warm / cold) replacing heuristic meta-governance. Engineering landing: v0.3 §3.6
   + §5.

6. **Language/process boundary** (v0.3 §10.4): `ReflexMonitor` (hot path, TCB)
   implemented in TypeScript inside the OpenClaw process for synchronous authority;
   `PlasticityEngine` and credit field live in the Python daemon (warm/cold path).
   Policies are expressed as a portable deterministic spec exported from OpenCOAT.

7. **Keep the cooperative bridge.** For unforked hosts, ADR-0011's bridge remains
   the integration path. Fork-based effector is an additional capability; both share
   wire protocol and concern semantics.

## Consequences

- `InhibitoryReflex` decisions gain real authority: `Deny` / `Rewrite` are enforced
  at the call site and fail-closed, closing the cooperative-enforcement gap.
- **Closed loop established**: `r_t` flows from `EffectorKernel` → `CreditField` →
  `PlasticityEngine`. Hard decisions yield clean credit (morphogenetic §9); soft
  advice credit remains statistically estimated. First time the system has a
  deterministic, measurable learning signal.
- The 2004 RAL/KBAL separation is reinstated as two **typed cell kinds** within one
  connectome, unified under one plasticity law — not two separate subsystems.
- The hexagonal seam (ADR-0006) gains an `EffectorReflexPort` so the core stays
  host-agnostic; the fork is one adapter behind it.
- The `(i)→(ii)` migration path (v0.3 §7) is non-destructive: start with one
  `ExcitatoryNeuron` + reflex ring, then widen (multi-neuron MoE) and deepen
  (`lift`: aspect-of-aspect) under the same plasticity law.
- Cost: fork drift vs upstream OpenClaw; TS/Python boundary requires portable policy
  spec; `ReflexMonitor` is safety-critical — a buggy TCB can deadlock the agent,
  hence the `A_reflex` invariants + JSONL replayability are load-bearing.

## References

- ADR-0002 (AOP as mechanism), ADR-0003 (host adapter as plugin),
  ADR-0006 (hexagonal ports), ADR-0008 (meta-concern governance),
  ADR-0011 (OpenClaw joinpoint model v0.1).
- **Engineering landing (v0.3 architecture)**:
  [`docs/design/v0.3-morphogenetic-architecture.md`](../design/v0.3-morphogenetic-architecture.md) —
  cell types §3, one-turn sequencing §4, three time scales §5, existing-package
  mapping §6, migration path §7, OpenClaw hook mapping §10.
- Reflex layer spec + interface contract + milestone roadmap:
  [`docs/design/self-built-effector-control-plane.md`](../design/self-built-effector-control-plane.md).
- Formal grounding:
  [`docs/design/morphogenetic-aspect-agent.md`](../design/morphogenetic-aspect-agent.md)
  §1 (`A_reflex` conserved core), §2 (`⇩_fast` turn), §3 (credit field `κ`),
  §5 (plasticity grammar), §9 (hard weaving = clean credit).
- 2004 paper (WAOSD'2004): RAL = spinal cord (deterministic reflex),
  KBAL = cortex (adaptive / synaptic plasticity).
