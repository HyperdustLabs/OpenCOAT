import type { AgentHookCtx } from "./types.js";
import type { Action, ReflexMonitor, State } from "./reflex-monitor.js";
import type { ToolGuardDecision } from "./injector.js";

export function buildToolCallAction(event: {
  toolName?: string;
  params?: Record<string, unknown>;
}): Action {
  return {
    kind: "tool_call",
    name: typeof event.toolName === "string" ? event.toolName : "tool",
    args:
      event.params && typeof event.params === "object"
        ? { ...event.params }
        : {},
    raw: event,
  };
}

export function buildReflexState(ctx: AgentHookCtx): State {
  return {
    session_id: ctx.sessionId ?? ctx.sessionKey ?? "default",
    turn_id: ctx.runId ?? ctx.sessionKey ?? "default",
    features: {
      agent_id: ctx.agentId,
      session_key: ctx.sessionKey,
    },
  };
}

/** Map ReflexMonitor output to OpenClaw ``before_tool_call`` hook return shape. */
export function reflexToolGuardDecision(
  monitor: ReflexMonitor,
  action: Action,
  state: State,
  params: Record<string, unknown>,
): ToolGuardDecision & { record?: ReturnType<ReflexMonitor["mediate"]>["record"] } {
  const { decision, record } = monitor.mediate(action, state);

  if (decision.kind === "deny") {
    return {
      block: true,
      blockReason: decision.reason,
      params,
      record,
    };
  }

  if (decision.kind === "rewrite") {
    return {
      block: false,
      params: decision.action.args,
      record,
    };
  }

  return { block: false, params, record };
}

/** Fail-closed when the monitor itself throws (TCB unavailable). */
export function failClosedToolGuard(
  params: Record<string, unknown>,
  err: unknown,
): ToolGuardDecision {
  const msg = err instanceof Error ? err.message : String(err);
  return {
    block: true,
    blockReason: `OpenCOAT ReflexMonitor fail-closed: ${msg}`,
    params,
  };
}
