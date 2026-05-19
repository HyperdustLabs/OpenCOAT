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

## M6 implementation (`feat/m6-lifecycle-workers`)

| PR slice | Status | Notes |
| --- | --- | --- |
| **PR1** decay + `ConflictScannerWorker` + scheduler | **in progress** | `DecayWorker`, `ConflictScannerWorker`, `HeartbeatLoop` maintenance hook, `Scheduler.start` in daemon |
| **PR2** merge + archive | pending | `merge_archiver.py` stub |
| **PR3** meta-review | pending | ADR-0008 governance loop |
| **PR4** 24h soak + example | pending | `examples/07_meta_governance_soak` |

**Next:** finish PR1 tests on CI, then merge/archive workers (PR2).
