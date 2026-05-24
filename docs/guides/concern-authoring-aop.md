# Concern authoring — AOP syntax (AspectJ) (ADR-0010)

OpenCOAT keeps **Concern** as the only unit. Author with `pointcuts[]` / `advices[]`;
legacy `pointcut` / `advice` / `weaving_policy` are optional and sync automatically.

## Minimal concern (tool guard)

```json
{
  "id": "shell-guard",
  "kind": "concern",
  "name": "Block rm -rf",
  "schema_version": "0.1.0",
  "pointcuts": [
    {
      "id": "pc-tool",
      "expression": "before_tool_call() && args(\"rm -rf\")"
    }
  ],
  "advices": [
    {
      "id": "adv-block",
      "kind": "before",
      "pointcut_ref": "pc-tool",
      "template": "tool_guard",
      "content": "Refusing destructive shell command.",
      "effect": {
        "mode": "block",
        "level": "tool_level",
        "target": "tool_call.arguments",
        "priority": 0.9
      }
    }
  ]
}
```

## Message-level guard (OpenClaw bridge)

The gateway bridge registers **29** plugin hooks plus **runtime observers** (`onAgentEvent`,
queue/task poll) for MVP joinpoints such as `queue.before_enqueue` (sync **block/rewrite**
on OpenClaw fork via `queue_before_enqueue`) and `reply_run.before_begin`
(observe-only — see [joinpoint model §4.1](../design/opencoat-openclaw-joinpoint-model-v0.1.md#41-mvp-emit-status-bridge-integrationsopenclaw-opencoat-bridge)).
Dogfood concerns: [`examples/09_queue_hook_dogfood`](../../examples/09_queue_hook_dogfood/README.md).

### Decision vs observe (OpenClaw fork + bridge)

Use the **HyperdustLabs fork** (`opencoat/hooks-v0.1`, see [openclaw-fork-dev.md](openclaw-fork-dev.md)) — not npm registry OpenClaw — for native queue hooks and dogfood.

| Class | Joinpoints (examples) | Host effect today |
| --- | --- | --- |
| **Decision** | `queue.before_enqueue`, `tool.before_call`, `subagent_spawning` → `task.before_create` | block, rewrite, spawn veto, prompt prepend, outbound cancel |
| **Observe** | `reply_run.*`, `planning.*`, `approval.requested`, `command.output_stream`, `patch.summary_created`, `error.detected`, queue poll fallback | DCN / activation only; no sync veto |

**Decision** = **collaborative guard** (bridge + daemon RPC; host applies advice). Not ADR-0012 **authoritative** in-proc `ReflexMonitor` fail-closed — see [v0.3 §10.5](../design/v0.3-morphogenetic-architecture.md#105-实现分期-2026-05).

**Next decision hooks** ship on the **same fork branch** (`tool_result_persist`, `reply_run.phase.*`, `response.before_final`, …) — not upstream `openclaw/openclaw`. See [fork hook backlog](openclaw-fork-dev.md#fork-hook-backlog-post-queue).

Prefer `user_message()` over flat `before_response` when the bridge sends `messages[]`:

```json
{
  "pointcuts": [
    {
      "id": "pc-user",
      "expression": "user_message() && args(\"shell\")"
    }
  ],
  "advices": [
    {
      "kind": "before",
      "pointcut_ref": "pc-user",
      "template": "response_requirement",
      "content": "Confirm scope before running shell tools."
    }
  ]
}
```

## Queue guard (OpenClaw fork + bridge)

Target `queue.before_enqueue` with explicit `joinpoints` (dotted names are not parsed
from `expression()` today). Bridge maps woven advice to OpenClaw `queue_before_enqueue`:

| `effect.target` | `effect.mode` | OpenClaw result |
| --- | --- | --- |
| `queue.prompt` | `block` | skip enqueue |
| `queue.prompt` | `rewrite` | replace queued prompt |
| `queue.summary_line` | `rewrite` | replace summary line |

```json
{
  "id": "oc.dogfood.queue-block",
  "pointcuts": [
    {
      "id": "pc-queue",
      "joinpoints": ["queue.before_enqueue"],
      "match": { "any_keywords": ["QUEUE_DOGFOOD_BLOCK"] }
    }
  ],
  "advices": [
    {
      "kind": "before",
      "pointcut_ref": "pc-queue",
      "template": "memory_write_guard",
      "content": "Follow-up queue blocked by policy.",
      "effect": {
        "mode": "block",
        "level": "memory_level",
        "target": "queue.prompt",
        "priority": 0.95
      }
    }
  ]
}
```

Full dogfood set: [`examples/09_queue_hook_dogfood`](../../examples/09_queue_hook_dogfood/README.md).

## Declare precedence

```json
{
  "id": "policy-strict",
  "declarations": [
    { "kind": "declare_precedence", "order": ["policy-strict", "policy-lenient"] }
  ]
}
```

Or a runtime edge: `relation_type: "declares_precedence_over"` (see concern schema).

## Python (`opencoat concern import`)

See `examples/05_aop_concerns/concerns.py` and `opencoat_runtime_cli.demo_concerns`.

Skill / install docs: after editing concerns, run `opencoat concern import <file.json>`
or `opencoat concern import --demo` against a running daemon (`uv run opencoat runtime up`).
