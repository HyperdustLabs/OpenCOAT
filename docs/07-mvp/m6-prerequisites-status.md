# M6 prerequisites — verification status

Tracked against [post-m5-roadmap §5A](./post-m5-roadmap.md#5a-m6-split-4-prs).
Re-run automation: `./scripts/verify-m6-prerequisites.sh` from repo root (daemon on
`127.0.0.1:7878`).

| ID | Gate | Status | Evidence |
| --- | --- | --- | --- |
| **P1** | Joinpoint hot path on `main` | **PASS** | `uv run pytest packages/opencoat-runtime/tests/core` |
| **P2a** | Daemon RPC smoke (`messages[]`, `#msg:`) | **PASS** | `./scripts/verify-m6-prerequisites.sh`; `user-shell-guard` in injections |
| **P2b** | Live OpenClaw gateway + bridge | **PASS** | 2026-05-18 local smoke — bridge README §3; NVDA concerns weave on `before_response` |
| **P3** | Conflict paths documented | **PASS** | [m6-conflict-paths.md](./m6-conflict-paths.md); [ADR-0010](../adr/0010-concern-aop-syntax.md) |

## M6 implementation

| PR slice | Status | Notes |
| --- | --- | --- |
| **PR1** decay + `ConflictScannerWorker` + scheduler | **merged** | [#72](https://github.com/HyperdustLabs/OpenCOAT/pull/72) |
| **PR2** merge + archive | **merged** | [#73](https://github.com/HyperdustLabs/OpenCOAT/pull/73) — `DCNEvolver`, `MergeArchiverWorker`, `HeartbeatMaintenance` config |
| **PR3** meta-review | **merged** (same PR) | `MetaReviewWorker` + `DefaultEvolutionControl` inventory |
| **PR4** soak + example | **merged** (same PR) | `tests/soak/`, `examples/07_meta_governance_soak` |

**Docs:** root [`README.md`](../../README.md) (M6 table + heartbeat section), [`examples/README.md`](../../examples/README.md) row 07, [`packages/opencoat-runtime/README.md`](../../packages/opencoat-runtime/README.md).

**Optional follow-up:** 24h live daemon soak for convergence metrics (hermetic soak already in CI).
