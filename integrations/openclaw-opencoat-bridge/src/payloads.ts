/**
 * Serialize OpenClaw plugin hook events into OpenCOAT joinpoint payloads.
 */

import { promptPayload } from "./messages.js";
import { textPayload } from "./daemon.js";

function safeJson(value: unknown, maxLen = 12_000): string {
  try {
    const s = JSON.stringify(value ?? null);
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen)}…`;
  } catch {
    return String(value);
  }
}

export function passThroughPayload(
  event: Record<string, unknown>,
  extra?: Record<string, unknown>,
): Record<string, unknown> {
  const text = safeJson({ ...event, ...extra });
  return { ...extra, text, raw_text: text, content: text, event };
}

export function toolCallPayload(event: {
  toolName?: string;
  params?: Record<string, unknown>;
}): Record<string, unknown> {
  const toolName = typeof event.toolName === "string" ? event.toolName : "tool";
  const params =
    event.params && typeof event.params === "object" ? { ...event.params } : {};
  const argText = JSON.stringify({ name: toolName, arguments: params });
  return textPayload(argText, toolName);
}

export function toolResultPayload(event: {
  toolName?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: string;
  durationMs?: number;
}): Record<string, unknown> {
  const toolName = typeof event.toolName === "string" ? event.toolName : "tool";
  const summary = safeJson({
    name: toolName,
    arguments: event.params,
    result: event.result,
    error: event.error,
    duration_ms: event.durationMs,
  });
  return {
    text: summary,
    raw_text: summary,
    content: summary,
    tool_name: toolName,
    error: event.error,
    stage: "after_tool",
  };
}

export function queuePayload(
  event: Record<string, unknown>,
  stage: "before_enqueue" | "after_enqueue",
): Record<string, unknown> {
  const text = safeJson(event);
  return {
    text,
    raw_text: text,
    content: text,
    stage,
    queue_key: event.queueKey,
    queue_mode: event.queueMode,
    drop_policy: event.dropPolicy,
    depth_before: event.depthBefore,
    depth_after: event.depthAfter,
    enqueued: event.enqueued,
    prompt: event.prompt,
    summary_line: event.summaryLine,
    message_id: event.messageId,
    originating_channel: event.originatingChannel,
    originating_to: event.originatingTo,
    originating_account_id: event.originatingAccountId,
    originating_thread_id: event.originatingThreadId,
    session_id: event.sessionId,
    session_key: event.sessionKey,
  };
}

export function messageContentPayload(
  content: string,
  extra?: Record<string, unknown>,
): Record<string, unknown> {
  const base = promptPayload({
    parts: content ? [content] : [],
    messages: content ? [{ role: "user", content }] : [],
  });
  return extra ? { ...base, ...extra } : base;
}

export function compactionPayload(
  event: Record<string, unknown>,
  phase: "before" | "after",
): Record<string, unknown> {
  const text = safeJson(event);
  return {
    text,
    raw_text: text,
    content: text,
    stage: phase === "before" ? "before_compaction" : "after_compaction",
    message_count: event.messageCount,
  };
}

export function subagentPayload(
  event: Record<string, unknown>,
  stage: string,
): Record<string, unknown> {
  const text = safeJson(event);
  return {
    text,
    raw_text: text,
    content: text,
    stage,
    child_session_key: event.childSessionKey,
    agent_id: event.agentId,
    label: event.label,
    mode: event.mode,
  };
}

export function llmPayload(
  event: Record<string, unknown>,
  phase: "input" | "output",
): Record<string, unknown> {
  const text = safeJson(event);
  return {
    text,
    raw_text: text,
    content: text,
    stage: phase === "input" ? "llm_input" : "llm_output",
  };
}
