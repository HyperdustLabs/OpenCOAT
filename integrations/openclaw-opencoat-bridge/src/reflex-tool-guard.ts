import { applyAgentMessageContent, extractAgentMessageText } from "./message-text.js";
import type { AgentHookCtx } from "./types.js";
import type { Action, ActionKind, ReflexMonitor, State } from "./reflex-monitor.js";
import type { ToolGuardDecision } from "./injector.js";

export function buildMemoryWriteAction(message: unknown): Action {
  const text = extractAgentMessageText(message);
  const role =
    message &&
    typeof message === "object" &&
    typeof (message as { role?: unknown }).role === "string"
      ? (message as { role: string }).role
      : "message";
  return {
    kind: "memory_write",
    name: role,
    args: { text, content: text, role },
    raw: message,
  };
}

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

export type ReflexDenyResult = {
  block: boolean;
  blockReason?: string;
  record?: ReturnType<ReflexMonitor["mediate"]>["record"];
};

export type MessageGuardDecision = {
  cancel?: boolean;
  content?: string;
  record?: ReturnType<ReflexMonitor["mediate"]>["record"];
};

/** Map ReflexMonitor output to OpenClaw ``message_sending`` (verify / repair). */
export function reflexMessageGuardDecision(
  monitor: ReflexMonitor,
  action: Action,
  state: State,
): MessageGuardDecision {
  const { decision, record } = monitor.mediate(action, state);
  if (decision.kind === "deny") {
    return { cancel: true, content: decision.reason, record };
  }
  if (decision.kind === "rewrite") {
    const content =
      typeof decision.action.args.content === "string"
        ? decision.action.args.content
        : undefined;
    if (content !== undefined) return { content, record };
  }
  return { record };
}

export type MemoryWriteDecision = {
  block?: boolean;
  message?: unknown;
  record?: ReturnType<ReflexMonitor["mediate"]>["record"];
};

export function reflexMemoryWriteDecision(
  monitor: ReflexMonitor,
  action: Action,
  state: State,
  rawMessage: unknown,
): MemoryWriteDecision {
  const { decision, record } = monitor.mediate(action, state);
  if (decision.kind === "deny") {
    return { block: true, record };
  }
  if (decision.kind === "rewrite") {
    const content =
      typeof decision.action.args.content === "string"
        ? decision.action.args.content
        : undefined;
    if (content !== undefined) {
      return {
        message: applyAgentMessageContent(rawMessage, content),
        record,
      };
    }
  }
  return { record };
}

export type ToolResultPersistDecision = {
  message?: unknown;
  record?: ReturnType<ReflexMonitor["mediate"]>["record"];
};

export function reflexToolResultPersistDecision(
  monitor: ReflexMonitor,
  action: Action,
  state: State,
  rawMessage: unknown,
): ToolResultPersistDecision {
  const { decision, record } = monitor.mediate(action, state);
  if (decision.kind === "deny") {
    return {
      message: applyAgentMessageContent(
        rawMessage,
        `[OpenCOAT blocked] ${decision.reason}`,
      ),
      record,
    };
  }
  if (decision.kind === "rewrite") {
    const content =
      typeof decision.action.args.content === "string"
        ? decision.action.args.content
        : undefined;
    if (content !== undefined) {
      return {
        message: applyAgentMessageContent(rawMessage, content),
        record,
      };
    }
  }
  return { record };
}

/** Generic deny-only ReflexMonitor path for spawn/message/queue hooks. */
export function reflexDenyDecision(
  monitor: ReflexMonitor,
  action: Action,
  state: State,
): ReflexDenyResult {
  const { decision, record } = monitor.mediate(action, state);
  if (decision.kind === "deny") {
    return {
      block: true,
      blockReason: decision.reason,
      record,
    };
  }
  return { block: false, record };
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

function failClosedReason(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  return `OpenCOAT ReflexMonitor fail-closed: ${msg}`;
}

/** Fail-closed when the monitor itself throws (TCB unavailable). */
export function failClosedToolGuard(
  params: Record<string, unknown>,
  err: unknown,
): ToolGuardDecision {
  return {
    block: true,
    blockReason: failClosedReason(err),
    params,
  };
}

export function failClosedMessageGuard(err: unknown): {
  cancel: true;
  content: string;
} {
  return { cancel: true, content: failClosedReason(err) };
}

export function failClosedSpawnGuard(err: unknown): {
  status: "error";
  error: string;
} {
  return { status: "error", error: failClosedReason(err) };
}

export function failClosedQueueGuard(err: unknown): {
  block: true;
  blockReason: string;
} {
  return { block: true, blockReason: failClosedReason(err) };
}

export function failClosedMemoryWriteGuard(err: unknown): { block: true } {
  void err;
  return { block: true };
}

export function failClosedToolResultPersistGuard(
  message: unknown,
  err: unknown,
): { message: unknown } {
  return {
    message: applyAgentMessageContent(
      message,
      `[OpenCOAT ReflexMonitor fail-closed] ${
        err instanceof Error ? err.message : String(err)
      }`,
    ),
  };
}
