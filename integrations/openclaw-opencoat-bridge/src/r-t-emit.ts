import type { AgentHookCtx, BridgeConfig } from "./types.js";
import type { DecisionRecord } from "./reflex-monitor.js";

export type RtSignalKind =
  | "tool_outcome"
  | "tool_blocked"
  | "llm_output"
  | "turn_complete";

export type RtRecordWire = {
  record_version: 1;
  event: "r_t";
  ts: string;
  session_id: string;
  turn_id: string;
  joinpoint: string;
  host: "openclaw";
  hook: string;
  signal: {
    kind: RtSignalKind;
    tool_name?: string;
    blocked?: boolean;
    error?: string;
    duration_ms?: number;
    reflex?: Record<string, unknown>;
    payload?: Record<string, unknown>;
  };
  r: number;
  baseline_b: number;
};

function sessionId(ctx: AgentHookCtx): string {
  return ctx.sessionId ?? ctx.sessionKey ?? "default";
}

function turnId(ctx: AgentHookCtx): string {
  return ctx.runId ?? ctx.sessionKey ?? "default";
}

export function buildToolBlockedRt(
  hook: string,
  joinpoint: string,
  ctx: AgentHookCtx,
  toolName: string,
  reflex?: DecisionRecord,
  reason?: string,
): RtRecordWire {
  return {
    record_version: 1,
    event: "r_t",
    ts: new Date().toISOString(),
    session_id: sessionId(ctx),
    turn_id: turnId(ctx),
    joinpoint,
    host: "openclaw",
    hook,
    signal: {
      kind: "tool_blocked",
      tool_name: toolName,
      blocked: true,
      error: reason,
      reflex: reflex ? { ...reflex } : undefined,
    },
    r: 0,
    baseline_b: 0,
  };
}

export function buildToolOutcomeRt(
  hook: string,
  joinpoint: string,
  ctx: AgentHookCtx,
  event: Record<string, unknown>,
  reflex?: DecisionRecord,
): RtRecordWire {
  const toolName =
    typeof event.toolName === "string" ? event.toolName : "tool";
  const error = typeof event.error === "string" ? event.error : undefined;
  const durationMs =
    typeof event.durationMs === "number" ? event.durationMs : undefined;
  const blocked = reflex?.decision === "deny";
  const success = !error && !blocked;

  return {
    record_version: 1,
    event: "r_t",
    ts: new Date().toISOString(),
    session_id: sessionId(ctx),
    turn_id: turnId(ctx),
    joinpoint,
    host: "openclaw",
    hook,
    signal: {
      kind: "tool_outcome",
      tool_name: toolName,
      blocked,
      error,
      duration_ms: durationMs,
      reflex: reflex ? { ...reflex } : undefined,
      payload: {
        has_result: event.result !== undefined,
      },
    },
    r: success ? 1 : 0,
    baseline_b: 0,
  };
}

export function buildLlmOutputRt(
  hook: string,
  joinpoint: string,
  ctx: AgentHookCtx,
  event: Record<string, unknown>,
): RtRecordWire {
  return {
    record_version: 1,
    event: "r_t",
    ts: new Date().toISOString(),
    session_id: sessionId(ctx),
    turn_id: turnId(ctx),
    joinpoint,
    host: "openclaw",
    hook,
    signal: {
      kind: "llm_output",
      payload: {
        text_len:
          typeof event.text === "string"
            ? event.text.length
            : typeof event.content === "string"
              ? event.content.length
              : 0,
      },
    },
    r: 1,
    baseline_b: 0,
  };
}

export function buildTurnCompleteRt(
  hook: string,
  joinpoint: string,
  ctx: AgentHookCtx,
  event: Record<string, unknown>,
): RtRecordWire {
  const error = typeof event.error === "string" ? event.error : undefined;
  return {
    record_version: 1,
    event: "r_t",
    ts: new Date().toISOString(),
    session_id: sessionId(ctx),
    turn_id: turnId(ctx),
    joinpoint,
    host: "openclaw",
    hook,
    signal: {
      kind: "turn_complete",
      error,
      payload: event,
    },
    r: error ? 0 : 1,
    baseline_b: 0,
  };
}

export async function appendRtRecord(
  cfg: BridgeConfig,
  record: RtRecordWire,
): Promise<void> {
  if (!cfg.enabled || !cfg.emitRtJsonl) return;

  const body = {
    jsonrpc: "2.0",
    method: "credit.r_t.append",
    id: `rt-${crypto.randomUUID()}`,
    params: { record },
  };

  try {
    await fetch(cfg.daemonUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    // Observe path — never block the host on r_t append failures.
  }
}

export function appendRtRecordFireAndForget(
  cfg: BridgeConfig,
  record: RtRecordWire,
): void {
  void appendRtRecord(cfg, record);
}
