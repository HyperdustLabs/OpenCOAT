/**
 * Sync-only OpenClaw hooks (before_message_write, tool_result_persist).
 * Handlers MUST NOT return Promises — fork ignores async results on these hooks.
 */

import type { ReflexRuntime } from "./reflex-policy-sync.js";
import type { BridgeConfig } from "./types.js";
import { extractAgentMessageText } from "./message-text.js";
import { buildPayloadAction } from "./reflex-policies.js";
import {
  buildMemoryWriteAction,
  buildReflexState,
  failClosedMemoryWriteGuard,
  failClosedToolResultPersistGuard,
  reflexMemoryWriteDecision,
  reflexToolResultPersistDecision,
} from "./reflex-tool-guard.js";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function syncCtx(ctx: unknown): {
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;
  runId?: string;
} {
  const c = asRecord(ctx);
  return {
    agentId: typeof c.agentId === "string" ? c.agentId : undefined,
    sessionKey: typeof c.sessionKey === "string" ? c.sessionKey : undefined,
    sessionId: typeof c.sessionId === "string" ? c.sessionId : undefined,
    runId: typeof c.runId === "string" ? c.runId : undefined,
  };
}

function monitorOrFailClosedMemory(
  runtime: ReflexRuntime | null,
  message: unknown,
): ReturnType<typeof reflexMemoryWriteDecision> | ReturnType<typeof failClosedMemoryWriteGuard> {
  if (!runtime) return failClosedMemoryWriteGuard(new Error("ReflexMonitor not initialized"));
  const action = buildMemoryWriteAction(message);
  return reflexMemoryWriteDecision(
    runtime.monitor,
    action,
    buildReflexState({}),
    message,
  );
}

function monitorOrFailClosedToolResult(
  runtime: ReflexRuntime | null,
  message: unknown,
  toolName?: string,
): ReturnType<typeof reflexToolResultPersistDecision> | ReturnType<typeof failClosedToolResultPersistGuard> {
  if (!runtime) {
    return failClosedToolResultPersistGuard(
      message,
      new Error("ReflexMonitor not initialized"),
    );
  }
  const text = extractAgentMessageText(message);
  const action = buildPayloadAction("tool_result_persist", {
    text,
    content: text,
    toolName: toolName ?? "tool",
  });
  return reflexToolResultPersistDecision(
    runtime.monitor,
    action,
    buildReflexState({}),
    message,
  );
}

export function handleBeforeMessageWriteSync(
  cfg: BridgeConfig,
  runtime: ReflexRuntime | null,
  event: unknown,
  ctx: unknown,
): { block?: boolean; message?: unknown } | undefined {
  if (!cfg.inProcReflexToolGuard && !cfg.inProcReflexGuards) return undefined;
  const ev = asRecord(event);
  const message = ev.message;
  const c = syncCtx(ctx);
  try {
    const decision = monitorOrFailClosedMemory(runtime, message);
    if (decision.block) return { block: true };
    if (decision.message !== undefined) {
      return { message: decision.message };
    }
    if (cfg.logActivations && decision.record?.policy_id) {
      // Sync path — no api.logger here; caller may log if needed.
      void c;
    }
    return undefined;
  } catch (err) {
    return failClosedMemoryWriteGuard(err);
  }
}

export function handleToolResultPersistSync(
  cfg: BridgeConfig,
  runtime: ReflexRuntime | null,
  event: unknown,
  ctx: unknown,
): { message?: unknown } | undefined {
  if (!cfg.inProcReflexToolGuard && !cfg.inProcReflexGuards) return undefined;
  const ev = asRecord(event);
  const message = ev.message;
  const c = syncCtx(ctx);
  const toolName = typeof ev.toolName === "string" ? ev.toolName : c.agentId;
  try {
    const decision = monitorOrFailClosedToolResult(runtime, message, toolName);
    if (decision.message !== undefined) {
      return { message: decision.message };
    }
    return undefined;
  } catch (err) {
    return failClosedToolResultPersistGuard(message, err);
  }
}

