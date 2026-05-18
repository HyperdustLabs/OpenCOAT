# M6 prerequisites — status

Tracking for [§5A prerequisites](./post-m5-roadmap.md#5a-m6-split-4-prs). Update when gates are re-run on a new machine or after breaking changes on `main`.

Re-run automation: `./scripts/verify-m6-prerequisites.sh` from repo root (daemon on `127.0.0.1:7878`).

| ID | Status | Notes |
| --- | --- | --- |
| **P1** | PASS | Core joinpoint / AOP tests on `main` — `uv run pytest packages/opencoat-runtime/tests/core` (see roadmap P1 row). |
| **P2a** | PASS | Daemon RPC smoke — `./scripts/verify-m6-prerequisites.sh`; `user-shell-guard` in injections; DCN `jp-m6-prereq-smoke#msg:1`. |
| **P2b** | PASS | Live OpenClaw smoke — 2026-05-18, local (bridge README §3 pass table). |
| **P3** | PASS | Activation-time `ConflictResolver` vs M6 `ConflictScannerWorker` — [m6-conflict-paths.md](./m6-conflict-paths.md), [ADR-0010](../adr/0010-concern-aop-syntax.md). |

## P2 — Live OpenClaw (2026-05-18)

Environment: OpenCOAT daemon on `:7878` (repo `packages/opencoat-runtime` via pipx editable), B.AI `gpt-5.2`, OpenClaw gateway `:18789`, bridge `@hyperdustlabs/opencoat-bridge` with `allowPromptInjection` + `logActivations`.

| Check | Result |
| --- | --- |
| `injections` non-empty on user shell question | PASS — TUI/curl: `How do I list files in shell safely?` |
| DCN `joinpoint_id` contains `#msg:` (`jp-oc-…#msg:N`) | PASS — e.g. `jp-oc-…#msg:0` on live turns |
| Harmless user line does not fire `user_message` guard | PASS — new session `tui-012536e6-…`, Tokyo weather only; no DCN row after `rm -rf` session (`16:02:43`) |
| `opencoat concern list` shows imported concern | PASS — `user-shell-guard`, demo set, etc. |

Counter-example nuance: re-scanning **earlier user rows** in the same `messages[]` still activates `#msg:0` (e.g. prior line containing `shell`). Use a **new session** or inspect `#msg:N` suffix when interpreting DCN.

See also: [bridge README §3](../../integrations/openclaw-opencoat-bridge/README.md#3-live-openclaw-verification-checklist), [B.AI + OpenClaw](../config/bai-llm.md#openclaw--bai).

**Next:** `feat/m6-lifecycle-workers` (decay + `ConflictScannerWorker`).
