# Post-M5 roadmap

> **Status**: active sequencing plan, opened after M5 closed (PRs
> [#28](https://github.com/HyperdustLabs/OpenCOAT/pull/28)–[#32](https://github.com/HyperdustLabs/OpenCOAT/pull/32)
> merged; close-out [#33](https://github.com/HyperdustLabs/OpenCOAT/pull/33)).
>
> **Scope**: locks the order of every PR between M5 and the end of M6.
> Three threads were on the table — the chosen sequence and the
> per-thread PR splits live below.
>
> **Source of truth wiring**: this doc is the *queue*. The
> [`milestones.md`](./milestones.md) table stays milestone-level
> (M0–M8); per-PR splits stay in [`CONTRIBUTING.md`](../../CONTRIBUTING.md);
> binding architecture decisions stay in [`adr/`](../adr/). Nothing
> here supersedes those — it just sequences them.

## 1. Where we are (post-M5)

- M0–M5 ✅ complete on `main` (see the milestones table linked above).
- Runtime can drive an OpenClaw-shaped host end-to-end via
  `opencoat_runtime_host_openclaw`
  (`adapter` + `injector` + `tool_guard` + `memory_bridge` +
  `install_hooks`); demo proven by `examples/04_openclaw_with_runtime`.
- CLI (`opencoat runtime|concern|dcn|inspect`) talks to the daemon over
  HTTP/JSON-RPC; `opencoat plugin install openclaw` scaffolds host stubs
  ([#37](https://github.com/HyperdustLabs/OpenCOAT/pull/37)); production
  OpenClaw uses the TS bridge
  ([`integrations/openclaw-opencoat-bridge/`](../../integrations/openclaw-opencoat-bridge/README.md)).
- Joinpoint hot path on `main` after [#64](https://github.com/HyperdustLabs/OpenCOAT/pull/64)–[#67](https://github.com/HyperdustLabs/OpenCOAT/pull/67):
  `JoinpointPipeline`, `JoinpointDiscovery`, bridge `messages[]`, AOP-shaped
  concerns (`pointcuts` / `advices` / `declarations`), activation-time
  `ConflictResolver` + `declare precedence` (full concern catalog).
- **P2 live OpenClaw** — PASS recorded 2026-05-18 ([`m6-prerequisites-status.md`](./m6-prerequisites-status.md));
  bridge README §3 pass table. M5 toy bus example remains for CI; §3 is the
  production-gateway gate before the 24 h soak.

## 2. Three candidate threads

### 2A. M6 mainline — Heartbeat + Meta governance workers

- Source: [`design/v0.2-system-design.md`](../design/v0.2-system-design.md) §12,
  [`milestones.md`](./milestones.md) row M6, and
  [`adr/0008-meta-concern-as-governance.md`](../adr/0008-meta-concern-as-governance.md).
- Exit criteria (unchanged): 24 h soak run; DCN converges; token budget
  stable; decay / conflict / merge / archive / meta-review jobs all wired.
- **Prerequisites** (gate before opening `feat/m6-lifecycle-workers`): see
  [§5A — M6 prerequisites](#5a-m6-split-4-prs).
- Touches: `opencoat_runtime_daemon/workers/*` + `scheduler.py`, wire
  `core/loops/heartbeat_loop.py` and `OpenCOATRuntime.tick`, `MetaConcern`
  governance under `core/meta/*`, admin surfaces in `opencoat`.
- Risk: invisible to non-runtime users; heaviest milestone so far;
  needs the soak harness and convergence metrics.

### 2B. DX sprint — make OpenCOAT immediately visible

Three sub-deliverables, each a small PR (no new packages):

1. **CLI banner** in `packages/opencoat-runtime/opencoat_runtime_cli`
   - `OpenCOAT` ASCII art (pyfiglet `big`, embedded as a constant — no
     runtime `pyfiglet` dependency).
   - Render once on `opencoat` invocation when `stdout.isatty()` and
     `NO_COLOR` is unset and `--no-banner` is not passed.
   - Subtitle line: daemon status + active profile + loaded host plugins.
   - `pyproject.toml` `description` flips to "OpenCOAT Runtime".
2. **`opencoat plugin install <host>`**
   - Generates `host_adapter.py` / `concerns.py` / `bootstrap_opencoat.py`
     stubs into a target dir (default cwd, `--out` override) for the
     `openclaw` and `custom` hosts.
   - Ships matching smoke test in `tests/cli/`.
3. **Three "dramatic" demo concerns**
   - `demo-tool-block` — `TOOL_GUARD` blocks `shell.exec rm -rf …`.
   - `demo-memory-tag` — annotates every memory write.
   - `demo-prompt-prefix` — rewrites the system-prompt prefix.
   - Loaded via `opencoat concerns load --demo`; cookbook section appended
     to `examples/04_openclaw_with_runtime/README.md`.

### 2C. External skill repo — `HyperdustLabs/opencoat-skill`

The installable skill lives **only** in [`HyperdustLabs/opencoat-skill`](https://github.com/HyperdustLabs/opencoat-skill); **this monorepo does not vendor a copy** under `integrations/`. Work in that repository (clone it locally), open PRs there, and redeploy the `www.opencoat.ai` worker per upstream [`DEPLOY.md`](https://github.com/HyperdustLabs/opencoat-skill/blob/main/DEPLOY.md) so CDN URLs stay fresh.

- Single GitHub repo (no `opencoat.ai` DNS yet — see §7).
- Contents: `SKILL.md`, `inspection.md`, `concerns.md`, `rules.md`,
  `skill.json`, `bootstrap_daemon.sh`, `LICENSE` (Apache-2.0), `.github/workflows/verify.yml`.
- Skill body wraps thread 2B: instructs the host agent to run
  `pipx install opencoat-runtime && opencoat plugin install openclaw`
  and points at the demo concerns from 2B.
- **Strict** dependency on 2B (no install affordance to wrap otherwise).

## 3. Dependency graph

```text
chain_ref schema ── (independent — protocol surface only)

2B-banner ──┐
2B-plugin ──┼──► 2C-skill-repo
2B-demos ──┘

2A-M6 (independent — touches runtime workers, not CLI/protocol)
```

- 2C blocks-on 2B.
- 2A is independent of 2B/2C and of `chain_ref`; it can run after.
- `chain_ref` is independent of everything else; landing it first
  removes future back-pressure on consumers.

## 4. Chosen sequence — A (DX-first)

1. ✅ **`feat/protocol-concern-chain-ref`** ([#35](https://github.com/HyperdustLabs/OpenCOAT/pull/35)) — optional `chain_ref`
   field on `Concern` (schema + pydantic model + tests). Schema-only
   placeholder, no business logic, no runtime consumers. Cheapest
   possible PR; got the protocol surface stable so MOSSAI / external
   callers can fill it later without schema churn. (See §6.)
2. ✅ **`feat/dx-cli-banner`** ([#36](https://github.com/HyperdustLabs/OpenCOAT/pull/36)) — banner + status subtitle + `--no-banner`.
3. ✅ **`feat/dx-plugin-install`** ([#37](https://github.com/HyperdustLabs/OpenCOAT/pull/37)) — `opencoat plugin install <openclaw|custom>`.
4. ✅ **`feat/dx-demo-concerns`** ([#38](https://github.com/HyperdustLabs/OpenCOAT/pull/38)) — three dramatic demo concerns
   + `opencoat concern import --demo`.
5. ✅ **[`HyperdustLabs/opencoat-skill`](https://github.com/HyperdustLabs/opencoat-skill)** — bootstrap commit batch in a
   *separate* repo (out-of-tree; not in this PR stream).
6. **M6 mainline** — satisfy [§5A prerequisites](#5a-m6-split-4-prs), then 4 PRs
   per the §5A split. ← **next up**

> Bonus mid-sprint: PRs [#39](https://github.com/HyperdustLabs/OpenCOAT/pull/39) +
> [#40](https://github.com/HyperdustLabs/OpenCOAT/pull/40) renamed the
> project COAT → OpenCOAT (packages, imports, binaries, env vars,
> deploy assets, schemas, telemetry, GitHub URLs, logo asset).
> Brand consistency is now 100% modulo two intentional fallbacks:
> the L21 acronym definition in `v0.1-complete-design.md`, and the
> demo concern matcher keywords that still recognise the legacy
> "COAT" spelling.

### Why A over alternatives

- **vs. B (M6-first, roadmap-strict)**: M5 produced no externally
  visible artifact; the DX sprint fixes that in three PRs. Landing M6
  first leaves OpenCOAT invisible for weeks while we grind on workers.
- **vs. C (parallel M6 + DX)**: rejected for one-author throughput;
  merge ordering between worker PRs and CLI PRs becomes annoying for
  no real schedule win.

## 5. Per-thread mini PR split

### 5A. M6 split (4 PRs)

#### M6 prerequisites

Complete **before** the first M6 implementation PR (`feat/m6-lifecycle-workers`).
These are sequencing gates, not part of the M6 exit criteria.

| # | Prerequisite | How to verify |
| --- | --- | --- |
| **P1** | Joinpoint **hot path** stable on current `main` | `JoinpointPipeline` + `JoinpointDiscovery`; bridge forwards `messages[]` on `before_prompt_build` ([#65](https://github.com/HyperdustLabs/OpenCOAT/pull/65)); AOP concern shape + activation-time `ConflictResolver` / `declare precedence` from full catalog ([#66](https://github.com/HyperdustLabs/OpenCOAT/pull/66), [#67](https://github.com/HyperdustLabs/OpenCOAT/pull/67)). `uv run pytest packages/opencoat-runtime/tests/core` green. |
| **P2** | **Live OpenClaw** smoke (not only in-tree `04_openclaw_with_runtime`) | Run daemon from repo `main` (`uv run opencoat runtime up`, not a stale pip wheel without discovery). Install bridge, restart gateway, walk [bridge README §3](../../integrations/openclaw-opencoat-bridge/README.md) pass table (`#msg:N` in DCN, `user_message` guard counter-example). Record pass/fail in a PR comment or issue — unblocks attributing soak failures to workers vs bridge/joinpoints. |
| **P3** | **Conflict paths** understood by implementers | **Activation-time:** `ConflictResolver` + `resolver/precedence.py` (already on `main`) drops losers per joinpoint. **Background (M6):** `ConflictScannerWorker` maintains DCN `conflicts_with` (and related) edges — do not re-implement precedence there; align with `core/meta/conflict_resolution.py` for Meta policy. |

**Out of scope for M6** (track as follow-up PRs after soak): multi-advice around
chains; full DCN export of AOP graph edges (`declares_precedence_over`); see
[`adr/0010-concern-aop-syntax.md`](../adr/0010-concern-aop-syntax.md).

#### M6 PR split

```text
gh/#?  feat/m6-lifecycle-workers   → decay + ConflictScannerWorker (DCN edges; ≠ ConflictResolver)
gh/#?  feat/m6-merge-archive       → merge + archive jobs + retention policy
gh/#?  feat/m6-meta-review         → meta-review loop + governance verdicts (per ADR-0008)
gh/#?  feat/m6-soak-and-example    → Scheduler.start + 24 h soak + examples/07_meta_governance_soak
```

Numbers will be assigned as PRs open, per the M5+ convention in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md).

### 5B. DX sprint split (3 PRs)

```text
gh/#36  feat/dx-cli-banner         → OpenCOAT banner + status subtitle + --no-banner             ✅ landed
gh/#37  feat/dx-plugin-install     → opencoat plugin install <openclaw|custom>                   ✅ landed
gh/#38  feat/dx-demo-concerns      → 3 dramatic concerns + opencoat concern import --demo        ✅ landed
```

> The concrete CLI verb shipped as ``opencoat concern import --demo``
> (mutually exclusive with ``<path>``) — chosen over a separate
> ``concerns load`` action so the demo set rides on the same
> ``concern.upsert`` RPC path that file imports already use.

### 5C. Skill repo (separate repo, not in this PR-stream)

- ✅ landed — [`HyperdustLabs/opencoat-skill`](https://github.com/HyperdustLabs/opencoat-skill)
  bootstrapped with the file set listed in §2C
  (`SKILL.md` + `skill.json` + `inspection.md` + `concerns.md` +
  `rules.md` + `LICENSE` + `.github/workflows/verify.yml`).
- Versioned to track `opencoat-runtime` major. The live `skill.json`
  still has `tracks: opencoat-runtime-cli@major` from before ADR 0009
  consolidated the CLI into the `opencoat-runtime` package; a
  trivial follow-up PR on the skill repo retargets it.
- CI green on first push; verifies `skill.json` shape, SKILL.md
  frontmatter + line count, and walks every internal link.

## 6. `Concern.chain_ref` — schema-only placeholder (active queue)

- Pulled out of the parked list because it is the cheapest way to
  freeze the protocol surface before MOSSAI / any third party tries to
  attach an on-chain reference.
- Shape (final wording locked in the PR):
  - Optional `chain_ref` object on `Concern` —
    `{network: string, ref: string, content_uri?: string}`.
  - Schema in `packages/opencoat-runtime-protocol/opencoat_runtime_protocol/schemas/concern.schema.json`
    (additive, default absent).
  - Pydantic mirror in the protocol package; nullable; no validators
    against networks/refs.
- Out of scope inside this PR: no resolver, no fetcher, no runtime
  consumer, no link to MOSSAI's `CognitiveNetworkTransport`.
- Rationale for landing first: protocol changes have the highest blast
  radius if they slip in late. One small PR pays the cost once.

## 7. Out of scope (parked)

- `opencoat.ai` landing page + dynamic `host.md?host=…` rendering —
  needs DNS + Pages + ongoing ops budget; deferred until ≥10 external
  users actually try the skill.
- MOSSAI / `CognitiveNetworkTransport` business logic / on-chain
  fetchers — belong in a separate L3 RFC under
  [`adr/`](../adr/) once OpenCOAT proves itself locally. The
  `chain_ref` field from §6 is the *only* concession to L3 in this
  queue.
- M7 (second host) and M8 (Postgres + K8s) — unchanged from
  [`milestones.md`](./milestones.md).

## 8. Risks & open questions

- **Banner pyfiglet dependency**: ASCII embedded as a constant → no
  runtime dep; pyfiglet only at author time. Confirmed in the
  `feat/dx-cli-banner` PR description.
- **`opencoat plugin install` output dir**: cwd default with `--out`
  override; directory-exists handling defers to the PR.
- **Demo concerns packaging**: ship inside `opencoat_runtime_cli` (no new
  package), gated by `--demo`.
- **M6 soak harness location**: `tests/soak/` (ephemeral) vs.
  `benchmarks/` (tracked). Decided in `feat/m6-soak-and-example`.
- **Skill repo license**: Apache-2.0 to match this repo.

---

When threads start landing, mark each PR row in §5 with the assigned
GitHub number and an `✅ landed` tag, mirroring the
`Suggested split for M*` style in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
