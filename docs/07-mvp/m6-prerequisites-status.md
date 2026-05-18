# M6 prerequisites — verification status

Tracked against [post-m5-roadmap §5A](./post-m5-roadmap.md#5a-m6-split-4-prs).
Re-run automation: `./scripts/verify-m6-prerequisites.sh` from repo root (daemon on
`127.0.0.1:7878`).

| ID | Gate | Status | Evidence |
| --- | --- | --- | --- |
| **P1** | Joinpoint hot path on `main` | **PASS** | `uv run pytest packages/opencoat-runtime/tests/core` (365 tests, 2026-05-18) |
| **P2a** | Daemon RPC smoke (`messages[]`, `#msg:`) | **PASS** | `./scripts/verify-m6-prerequisites.sh`; `user-shell-guard` in injections; DCN `jp-m6-prereq-smoke#msg:1` |
| **P2b** | Live OpenClaw gateway + bridge | **PARTIAL** | `@hyperdust/opencoat-bridge` loaded from `~/COAT/integrations/openclaw-opencoat-bridge`; gateway log `[opencoat-bridge] registered`. Telegram/TUI §3 checklist not recorded here. |
| **P2c** | `user_message` counter-example | **PASS** | Harmless user line + assistant `rm -rf` in history does not activate `user-shell-guard` (RPC counter in script) |
| **P3** | Conflict paths documented | **PASS** | [m6-conflict-paths.md](./m6-conflict-paths.md); [ADR-0010](../adr/0010-concern-aop-syntax.md) updated |

**Next:** open `feat/m6-lifecycle-workers` after P2b live chat is checked (optional
but recommended before 24 h soak).
