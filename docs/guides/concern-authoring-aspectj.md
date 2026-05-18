# Concern authoring — AspectJ syntax (ADR-0010)

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

See `examples/05_aspectj_concerns/concerns.py` and `opencoat_runtime_cli.demo_concerns`.

Skill / install docs: after editing concerns, run `opencoat concern import <file.json>`
or `opencoat concern import --demo` against a running daemon (`uv run opencoat runtime up`).
