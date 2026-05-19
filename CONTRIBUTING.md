# Contributing to OpenCOAT Runtime

Thank you for working on OpenCOAT. This document captures **how we change the
codebase** so the milestones in
[`docs/design/v0.2-system-design.md`](docs/design/v0.2-system-design.md) §12
land cleanly and reviewably, while **feature priority** stays grounded in
user-visible outcomes (see *Prioritization: user stories → use cases* below).

> Audience: humans and AI coding agents collaborating on this repo.
> Active from **M1 onwards**. M0 was a one-shot scaffold.
>
> **Agents:** never `git push origin main`. Use a feature branch + PR every time;
> see [`.cursor/rules/contributing-pr-only.mdc`](.cursor/rules/contributing-pr-only.mdc)
> and the **Monorepo git workflow** section in the installed
> [OpenCOAT skill](https://www.opencoat.ai/SKILL.md) (`~/.cursor/skills/opencoat/SKILL.md`).

---

## TL;DR

```bash
git switch -c <branch>             # see naming below
# ... edit ...
./scripts/verify.sh                # local mirror of CI
git push -u origin HEAD             # opens PR on GitHub
# fill the PR template, wait for CI green, squash-merge
```

Direct pushes to `main` are no longer permitted from M1 on. Even single
commits go through a PR — that's our paper trail and CI gate.

---

## Prioritization: user stories → use cases → MVP (over full-architecture stubs)

The v0.2 layout maps every `opencoat_runtime_core/` module to a **design**
section (§20 / §22). The **milestone table** (§12 / [`docs/07-mvp/milestones.md`](docs/07-mvp/milestones.md))
phases delivery (daemon, persistence, hosts, soak, …). Those two are **not**
the same as a per-file implementation checklist: some modules stay stubs until
a story needs them.

**How we decide what to build next**

1. **User story first** — one or two sentences: who (host operator / integrator
   / end user), what observable behaviour changes, why it matters. Prefer a
   runnable example or skill path over abstract completeness.
2. **Split the story into use cases** — each **use case** is a concrete slice
   you can implement and test on its own. Prefer a small table or bullet list
   in the issue / PR description, each row containing:
   - **Title** — short verb phrase (e.g. “Operator sees activation in DCN log”).
   - **Actor** — who drives the flow (same as or narrower than the story’s “who”).
   - **Preconditions** — daemon up, concern imported, host plugin installed, …
   - **Main flow** — 3–7 steps (CLI commands, RPC methods, or UI/host actions).
   - **Success criteria** — observable outcome (log line, JSON field, blocked
     tool, prompt prefix present, test assertion).
   Stories that are too big for one PR should break across **multiple use
   cases**; the **MVP** picks one use case (or a minimal chain) to ship first,
   not the whole story at once.
3. **MVP slice** — the smallest change that closes **at least one use case**
   end-to-end (often one joinpoint surface, one store path, or one CLI/RPC
   affordance). If the design doc lists ten modules for a pipeline, ship the
   **narrow vertical** that satisfies that use case’s success criteria before
   filling every sibling stub.
4. **Feedback** — issues, PR discussion, or dogfood notes; capture regressions
   and “almost works” gaps per use case.
5. **Enhance** — add further use cases from the same story, then generalise,
   harden, or align with the broader §20 plan once the MVP path is proven.

**Milestones still matter** for cross-cutting gates (CI, persistence, daemon,
host adapters, soak). When a milestone row and a user story (or a specific **use
case**) disagree on priority, **the story / use case wins for product
behaviour**; update the milestone text or open a scoped follow-up PR rather
than deferring user-visible fixes to “when the whole §20 tree is done.”

---

## 1. Branching model

- `main` is always green and always deployable in spirit.
- All work happens on short-lived feature branches off `main`.

Branch names follow:

| Prefix | Use case | Example |
|---|---|---|
| `feat/`  | new capability scoped to a milestone task | `feat/m1-extractor` |
| `fix/`   | bug fix | `fix/copr-tokenizer-empty-input` |
| `docs/`  | docs / ADR only | `docs/adr-0009-vector-index` |
| `chore/` | tooling / CI / deps | `chore/ruff-0.16` |
| `refactor/` | non-behavioural cleanup | `refactor/coordinator-priority` |
| `test/`  | tests-only addition | `test/integration-turn-loop` |

Branches should die after merging — we squash-merge and delete the branch.

---

## 2. PR size & shape

- **Target ≤ 1000 lines of diff.** If a milestone task naturally exceeds
  this, split it up front (see the M1 plan below for an example).
- One PR per coherent concern. "Add extractor + fix unrelated typo +
  rename CLI flag" is three PRs.
- Every PR fills the [pull request template](.github/pull_request_template.md).
  The checklists are not decorative — they encode the contract.

> Each row maps a milestone task (the `PR-N` index used inside this
> roadmap) to the matching GitHub pull request (`gh/#N`). The two
> sequences differ — GitHub numbers cover docs, chore, and follow-up
> fix PRs that aren't part of the milestone plan — so we keep both.

### Suggested split for M1 (✅ landed)

```text
PR-1  gh/#1   feat/m1-concern-store      → memory ConcernStore + MemoryDCNStore
PR-2  gh/#2   feat/m1-joinpoint-pointcut → joinpoint catalog + 12 pointcut strategies
PR-3  gh/#3   feat/m1-coordinator        → coordinator / resolver / vector
PR-4  gh/#4   feat/m1-advice-weaver      → advice generator + weaver + verifier
PR-5  gh/#5   feat/m1-turn-loop          → wire facade.on_joinpoint end to end
PR-6  gh/#6   feat/m1-example-chat       → examples/01_simple_chat_agent
```

### Suggested split for M2 (✅ landed)

```text
PR-7  gh/#7   feat/m2-openai-client      → OpenAILLMClient                                       ✅ landed
PR-8  gh/#9   feat/m2-anthropic-client   → AnthropicLLMClient                                    ✅ landed
PR-9  gh/#11  feat/m2-azure-client       → AzureOpenAILLMClient + provider matrix                ✅ landed
PR-10 gh/#12  feat/m2-extractor          → ConcernExtractor (NL governance docs → Concern)       ✅ landed
PR-11 gh/#13  feat/m2-lifecycle          → ConcernLifecycleManager (reinforce/weaken/archive/revive) ✅ landed
PR-12 gh/#14  feat/m2-coding-agent       → examples/02_coding_agent_demo (real LLM)              ✅ landed
```

### Suggested split for M3 (✅ landed)

```text
PR-13 gh/#15  feat/m3-sqlite-concern-store → SqliteConcernStore                                  ✅ landed
PR-14 gh/#16  feat/m3-sqlite-dcn-store     → SqliteDCNStore (graph rows + traversal)             ✅ landed
PR-15 gh/#18  feat/m3-jsonl-replay         → append-only event log + replay tool                 ✅ landed
PR-16 gh/#20  feat/m3-persistence-example  → examples/03_persistent_agent_demo                   ✅ landed
```

### Suggested split for M4 (✅ landed)

```text
PR-17 gh/#21  feat/m4-runtime-builder    → DaemonConfig → OpenCOATRuntime factory (storage + LLM selector) ✅ landed
PR-18 gh/#22  feat/m4-jsonrpc-handler    → in-proc JSON-RPC method dispatch (pure)               ✅ landed
PR-19 gh/#23  feat/m4-http-server        → stdlib HTTP server mounting the JSON-RPC handler      ✅ landed
PR-20 gh/#24  feat/m4-daemon-lifecycle   → Daemon.start/stop/reload + SIGTERM drain + PID file   ✅ landed
PR-21 gh/#25  feat/m4-cli-runtime        → opencoat runtime up|down|status (HTTP client)            ✅ landed
PR-22 gh/#26  feat/m4-cli-concern-dcn    → opencoat concern + dcn + inspect (HTTP client)           ✅ landed
PR-23 gh/#27  feat/m4-example-daemon     → examples/06_long_running_daemon end-to-end            ✅ landed
```

PRs land in order; each one keeps `main` green. Why the gaps in the
`gh/#` column? GitHub PRs `#8` (docs/m1-m2-progress), `#10` (chore
post-PR-8 doc sync), `#17` (closed README patch), and `#19` (JSONL
header reopen fix) sit between milestone tasks — they're real PRs but
not part of the milestone plan.

### Suggested split for M5 (✅ landed)

```text
gh/#28  feat/m5-openclaw-adapter        → OpenClawEvent + joinpoint_map + adapter.map_host_event(s) ✅ landed
gh/#29  feat/m5-openclaw-injector       → ConcernInjection → OpenClaw context (per weaving target) + span_extractor ✅ landed
gh/#30  feat/m5-openclaw-tool-guard     → AdviceType.TOOL_GUARD on tool_call.arguments (mutate / block) ✅ landed
gh/#31  feat/m5-openclaw-memory-bridge  → memory_bridge + install_hooks() lifecycle binding ✅ landed
gh/#32  feat/m5-example-openclaw        → examples/04_openclaw_with_runtime end-to-end + integration test ✅ landed
```

The PR-N parallel index is gone from M5 onwards (see the "Milestone PR
numbering convention (M5+)" section above): milestone tasks **are** the
GitHub PR numbers.

---

## 3. Local verification (mandatory before opening a PR)

```bash
./scripts/verify.sh
```

This runs exactly what CI runs:

1. `uv sync --all-extras --dev`
2. `uv run ruff check .`
3. `uv run ruff format --check .`
4. `uv run python tools/schema_check.py`
5. `uv run pytest`

If a step fails, fix it before pushing — CI will reject the same way and
your reviewer's time is more valuable than yours.

---

## 4. What requires extra care

These changes always need an explicit reviewer sign-off:

- Anything under `packages/opencoat-runtime-protocol/opencoat_runtime_protocol/schemas/`
  — schemas are wire format. Bump `schema_version` if you change semantics
  and call out migration in the PR description.
- `packages/opencoat-runtime/opencoat_runtime_core/runtime.py`
  — the `OpenCOATRuntime` facade. Every host adapter and the daemon depend on
  these signatures.
- `packages/opencoat-runtime/opencoat_runtime_core/ports/*.py`
  — hexagonal ports. Adapter implementations across `storage`, `llm`, and
  `host-plugins` will follow.
- Any change to or addition of an ADR under [`docs/adr/`](docs/adr/).
  Architecture decisions are binding — supersede an ADR with a new ADR,
  don't silently rewrite history.
- Anything that affects a milestone's exit criteria.
- **Feature scope** defaults to the **Prioritization: user stories → use cases → MVP**
  section above — if a change closes a user-visible gap ahead of a broad
  milestone row, say so in the PR description (name the **use case** and its
  success criteria when helpful).

For purely additive changes inside a single package (e.g. a new private
helper module), reviewer scrutiny is lighter.

---

## 5. Commit messages

Use Conventional-Commits-flavoured prefixes. The same vocabulary as the
branch prefixes:

```text
<type>(<scope>): <subject>

<optional body>
```

Examples seen in this repo:

```text
M0: monorepo skeleton, schemas, core, packages, CI
docs(readme): shorten hero title to OpenCOAT
chore(github): add pull request template
```

Body is optional but encouraged when explaining *why*.

---

## 6. Code style

Enforced automatically:

- `ruff check` (lint)
- `ruff format` (formatter)

Configured in [`pyproject.toml`](pyproject.toml). If a rule is wrong for
your case, add a tightly-scoped `# noqa: <code>` rather than disabling the
rule globally.

Type annotations: required on public APIs. Internal helpers may go without
when the type is obvious. We don't run `mypy --strict` yet (planned for
M2+) but please keep the types accurate so the future tightening is cheap.

---

## 7. Tests

- Every new module ships at least one test (smoke import + behavioural).
- `pytest --import-mode=importlib` is in effect — name your test files
  `test_<scope>.py` to keep them globally unique.
- For protocol changes, add round-trip tests under
  `packages/opencoat-runtime-protocol/tests/`.
- Cross-package integration tests go under `tests/integration/`.

---

## 8. ADRs

Significant architectural choices live under [`docs/adr/`](docs/adr/) as
numbered Markdown files. To add a new one:

1. Pick the next number (currently 0009 onwards).
2. Use an existing ADR as the template (`docs/adr/0001-…` is short and clear).
3. Cite the ADR from the PR description so reviewers see the rationale up front.

---

## 9. Branch protection on `main`

Configured in GitHub *Settings → Branches → Branch protection rules*:

- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging
  - Required jobs: `Test (Python 3.11)`, `Test (Python 3.12)`, `Schema validation (no Python code)`
- ✅ Require branches to be up to date before merging
- ✅ Require linear history
- ✅ Restrict who can push (no direct pushes)
- ❌ Allow force pushes (off)
- ❌ Allow deletions (off)

Reviewer count is left at 0 in this single-human-plus-agent stage — the
gate is CI + the PR template's self-review checklist. Add a required
reviewer once a third collaborator joins.

---

## 10. Releasing

Out of scope until M2+. Follow the placeholder
[`scripts/release.sh`](scripts/release.sh) when we get there.
