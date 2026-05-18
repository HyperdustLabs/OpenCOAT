# M6 implementer note — conflict and precedence paths

Two separate mechanisms apply at different times. Do not merge them in one worker.

## Activation-time (joinpoint hot path) — already on `main`

| Piece | Location | Role |
| --- | --- | --- |
| Rank + budget | `ConcernCoordinator` → `ConcernRanker` | Score candidates |
| Hard drops | `ConflictResolver` (`resolver/conflict.py`) | `conflicts_with`, `suppresses`, AOP `declare precedence` |
| Precedence map | `resolver/precedence.py` | Built from **full concern catalog** (`concern_catalog` from `JoinpointPipeline`) |
| Meta policy hook | `meta/conflict_resolution.py` | Stub — M6 meta-review may call after scanner proposes pairs |

**M6 workers must not** re-run precedence drops on every heartbeat tick.

## Background (M6 — to implement)

| Piece | Location | Role |
| --- | --- | --- |
| Scheduler | `opencoat_runtime_daemon/scheduler.py` | Periodic `runtime.tick` |
| Conflict scanner | `workers/conflict_scanner.py` | Discover concern pairs; write DCN `conflicts_with` (and related) edges |
| Decay / merge / archive | `workers/decay_worker.py`, `merge_archiver.py` | DCN evolution per ADR-0008 / lifecycle meta |
| Heartbeat inventory | `loops/heartbeat_loop.py` | Today counts concerns only; M6 wires real walkers |

**ConflictScannerWorker** maintains the graph for analytics and meta-review; it does
not replace `ConflictResolver` at weave time.

## Authoring

- Prefer `declarations[]` / `declares_precedence_over` over `suppresses` for ordering
  ([ADR-0010](../adr/0010-concern-aop-syntax.md)).
- Policy-only concerns (no pointcut) may still declare precedence; catalog must be
  passed into `ConflictResolver.resolve(..., concern_catalog=...)`.

## Follow-ups (not M6 exit criteria)

- Multi-advice around ordering chain
- DCN export of AOP graph edges (`declares_precedence_over`)
