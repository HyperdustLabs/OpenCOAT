# OpenClaw fork development (1:1 with global CLI)

OpenCOAT + OpenClaw bridge development uses the **HyperdustLabs fork**, not npm
registry OpenClaw or the upstream `openclaw/openclaw` main tree.

| Item | Canonical path |
| --- | --- |
| Fork repo | `~/openclaw-fork` |
| Remote | `https://github.com/HyperdustLabs/openclaw.git` |
| Branch | `opencoat/hooks-v0.1` |
| Lock file | `~/.openclaw/openclaw-fork.json` |

## Policy

1. **Global `openclaw` must be 1:1 with `~/openclaw-fork`** — same commit, same
   `openclaw.mjs`, same `dist/index.js`. No separate npm registry install.
2. **Gateway LaunchAgent** must run `~/openclaw-fork/dist/index.js` (port 18789).
3. **Do not use** `~/openclaw` (upstream clone) for OpenCOAT dogfood — it lacks
   queue hooks and fork-specific plugin SDK surfaces.
4. After every `git pull` in the fork, re-run bind + rebuild.

## One-time setup

From OpenCOAT repo root:

```bash
./scripts/use-openclaw-fork.sh --clone   # if ~/openclaw-fork missing
# or, if fork already exists:
./scripts/use-openclaw-fork.sh
```

This:

- `npm install -g .` from `~/openclaw-fork` (symlink, not registry copy)
- installs `~/.local/bin/openclaw` → `openclaw-fork` shim
- reinstalls LaunchAgent gateway on fork `dist/`
- writes `~/.openclaw/openclaw-fork.json`

## Daily workflow

```bash
cd ~/openclaw-fork
git pull origin opencoat/hooks-v0.1
# ... edit, commit, push to HyperdustLabs/openclaw ...

cd /path/to/OpenCOAT
./scripts/use-openclaw-fork.sh --update   # pull + pnpm install + build + rebind
./scripts/check-openclaw-fork.sh          # verify 1:1
```

Bridge rebuild after TS changes:

```bash
cd integrations/openclaw-opencoat-bridge && npm run build
openclaw daemon restart
```

## Verify

```bash
./scripts/check-openclaw-fork.sh
openclaw --version                        # e.g. 2026.5.19 (593c5de)
openclaw gateway status                   # CLI version == Gateway version
# Command line should include: ~/openclaw-fork/dist/index.js
```

## What breaks 1:1 alignment

| Action | Fix |
| --- | --- |
| `npm install -g openclaw@latest` (registry) | `./scripts/use-openclaw-fork.sh` |
| Running gateway from `/tmp/...` without updating LaunchAgent | `openclaw gateway install --force` |
| Fork pulled but not rebuilt | `cd ~/openclaw-fork && pnpm build` then `./scripts/use-openclaw-fork.sh` |
| Old BAIclaw shim on PATH | removed by `use-openclaw-fork.sh`; use fork shim only |

## Fork hook backlog (post-queue)

After [PR #77](https://github.com/HyperdustLabs/OpenCOAT/pull/77) (queue `queue_before_enqueue` / `queue_after_enqueue` + bridge `queue_guard`) lands on `main`, plan **paired fork + OpenCOAT PRs** on `opencoat/hooks-v0.1`:

| Priority | Fork hook / joinpoint | Notes |
| --- | --- | --- |
| 1 | `tool_result_persist` | Fork hook is **sync-only** today; needs async or local policy cache before bridge can weave |
| 2 | `reply_run.phase.*` | Native hooks at `ReplyOperation` phase edges (not lifecycle approx) |
| 3 | `response.before_final` | Unified verifier before channel delivery (beyond `message_sending` cancel) |
| 4 | `memory.before_write` | Unified memory middleware (compaction hooks are observe-only today) |
| 5 | `queue.before_drain` | Wrap `scheduleFollowupDrain` |

Bridge skipped (fork has hook, hot path): `before_message_write`, `tool_result_persist` until sync/async contract is extended.

## Troubleshooting queue guard

If gateway logs show `unknown typed hook "queue_before_enqueue" ignored`, the running
gateway is **not** on fork `dist/` (stale LaunchAgent or registry OpenClaw). Queue sync
veto/rewrite will **not** run; poll fallback may still emit observe-only
`queue.before_enqueue` to DCN.

```bash
./scripts/check-openclaw-fork.sh
openclaw gateway status    # CLI version == Gateway version; cmdline uses ~/openclaw-fork/dist/index.js
grep opencoat-bridge ~/.openclaw/logs/gateway.log   # expect "registered 29 hooks", no queue hook ignored
```

**v0.3 (i) note:** queue guard on fork is the first **collaborative** effect-boundary
pilot ([v0.3 §10.5](../design/v0.3-morphogenetic-architecture.md#105-实现分期-2026-05),
[examples/09_queue_hook_dogfood](../../examples/09_queue_hook_dogfood/README.md)). In-proc
authoritative `ReflexMonitor` is the next step, not done today.

## Related

- [OpenClaw bridge README](../../integrations/openclaw-opencoat-bridge/README.md)
- [Joinpoint model §4.1 queue hooks](../design/opencoat-openclaw-joinpoint-model-v0.1.md)
- HyperdustLabs PR: `opencoat/hooks-v0.1` on `HyperdustLabs/openclaw`
