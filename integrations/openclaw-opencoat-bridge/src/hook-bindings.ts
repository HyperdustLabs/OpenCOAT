/**
 * OpenClaw plugin hook → OpenCOAT joinpoint bindings (ADR-0011).
 *
 * Legacy OpenClaw queue observations still use runtime-observers.ts
 * (queue-depth poll). Native queue hooks are registered here when present.
 *
 * Skipped (sync hot path — cannot await daemon RPC):
 *   before_message_write, tool_result_persist
 * Skipped (install-only):
 *   before_install
 */

export type HookKind =
  | "observe"
  | "prompt_fold"
  | "tool_guard"
  | "message_out"
  | "subagent_spawn"
  | "queue_guard"
  | "buffer_input";

export type HookBinding = {
  hook: string;
  joinpoint: string;
  kind: HookKind;
};

/** All hooks the bridge registers. */
export const HOOK_BINDINGS: HookBinding[] = [
  // --- already wired (kept for documentation order) ---
  { hook: "session_start", joinpoint: "runtime_start", kind: "observe" },
  { hook: "message_received", joinpoint: "on_user_input", kind: "buffer_input" },
  { hook: "before_prompt_build", joinpoint: "before_response", kind: "prompt_fold" },
  { hook: "before_tool_call", joinpoint: "before_tool_call", kind: "tool_guard" },

  // --- model / agent turn ---
  { hook: "before_model_resolve", joinpoint: "before_reasoning", kind: "observe" },
  { hook: "before_agent_start", joinpoint: "before_reasoning", kind: "observe" },
  { hook: "before_agent_reply", joinpoint: "before_response", kind: "observe" },
  { hook: "llm_input", joinpoint: "before_reasoning", kind: "observe" },
  { hook: "llm_output", joinpoint: "after_reasoning", kind: "observe" },
  { hook: "agent_end", joinpoint: "after_response", kind: "observe" },

  // --- session / gateway ---
  { hook: "session_end", joinpoint: "runtime_stop", kind: "observe" },
  { hook: "gateway_start", joinpoint: "runtime_start", kind: "observe" },
  { hook: "gateway_stop", joinpoint: "runtime_stop", kind: "observe" },
  { hook: "before_reset", joinpoint: "runtime_recovery", kind: "observe" },

  // --- messages / dispatch ---
  { hook: "before_agent_run", joinpoint: "input.received", kind: "observe" },
  { hook: "inbound_claim", joinpoint: "on_user_input", kind: "observe" },
  { hook: "before_dispatch", joinpoint: "on_user_input", kind: "observe" },
  { hook: "reply_dispatch", joinpoint: "before_response", kind: "observe" },
  { hook: "message_sending", joinpoint: "before_response", kind: "message_out" },
  { hook: "message_sent", joinpoint: "after_response", kind: "observe" },

  // --- tools ---
  { hook: "after_tool_call", joinpoint: "after_tool_call", kind: "observe" },

  // --- queue ---
  { hook: "queue_before_enqueue", joinpoint: "queue.before_enqueue", kind: "queue_guard" },
  { hook: "queue_after_enqueue", joinpoint: "queue.after_enqueue", kind: "observe" },

  // --- memory / compaction ---
  { hook: "before_compaction", joinpoint: "before_memory_write", kind: "observe" },
  { hook: "after_compaction", joinpoint: "after_memory_write", kind: "observe" },

  // --- subagents / tasks ---
  { hook: "subagent_spawning", joinpoint: "task.before_create", kind: "subagent_spawn" },
  { hook: "subagent_delivery_target", joinpoint: "task.after_create", kind: "observe" },
  { hook: "subagent_spawned", joinpoint: "task.after_create", kind: "observe" },
  { hook: "subagent_ended", joinpoint: "task.before_terminal", kind: "observe" },
];

export const SKIPPED_HOOKS = [
  "before_message_write",
  "tool_result_persist",
  "before_install",
] as const;

export function bindingForHook(hook: string): HookBinding | undefined {
  return HOOK_BINDINGS.find((b) => b.hook === hook);
}
