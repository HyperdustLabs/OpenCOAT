import type {
  AgentHookCtx,
  BridgeConfig,
  ConcernExtractResult,
  ConcernInjection,
  JoinpointWire,
} from "./types.js";
import {
  parseReflexPolicyExport,
  type ReflexPolicySpec,
} from "./reflex-policy-spec.js";

const JOINPOINT_LEVEL_RUNTIME = 0;
const JOINPOINT_LEVEL_LIFECYCLE = 1;

export function resolveConfig(raw: Record<string, unknown> | undefined): BridgeConfig {
  const daemonUrl =
    (typeof raw?.daemonUrl === "string" && raw.daemonUrl.trim()) ||
    "http://127.0.0.1:7878/rpc";
  const observerPollMs =
    typeof raw?.observerPollMs === "number" && raw.observerPollMs >= 100
      ? raw.observerPollMs
      : 500;
  return {
    daemonUrl,
    enabled: raw?.enabled !== false,
    logActivations: raw?.logActivations === true,
    extractOnUserMessage: raw?.extractOnUserMessage === true,
    runtimeObservers: raw?.runtimeObservers !== false,
    observerPollMs,
    inProcReflexToolGuard: raw?.inProcReflexToolGuard === true,
    inProcReflexGuards:
      raw?.inProcReflexGuards === true || raw?.inProcReflexToolGuard === true,
    reflexSyncFromDaemon: raw?.reflexSyncFromDaemon !== false,
    reflexAuditToDaemon: raw?.reflexAuditToDaemon !== false,
    reflexPolicies: parseInlineReflexPolicies(raw?.reflexPolicies),
    reflexIncludeDemoPolicy: raw?.reflexIncludeDemoPolicy !== false,
    emitRtJsonl:
      raw?.emitRtJsonl === true ||
      (raw?.emitRtJsonl !== false && raw?.inProcReflexToolGuard === true),
  };
}

function parseInlineReflexPolicies(raw: unknown): ReflexPolicySpec[] {
  const parsed = parseReflexPolicyExport(
    raw && typeof raw === "object" && Array.isArray((raw as { policies?: unknown }).policies)
      ? { version: "0.1", policies: (raw as { policies: unknown[] }).policies }
      : Array.isArray(raw)
        ? { version: "0.1", policies: raw }
        : null,
  );
  return parsed?.policies ?? [];
}

export function runKey(ctx: AgentHookCtx): string {
  return ctx.runId ?? ctx.sessionId ?? ctx.sessionKey ?? "default";
}

export function newJoinpointId(): string {
  return `jp-oc-${crypto.randomUUID()}`;
}

export async function extractConcernsFromChat(
  cfg: BridgeConfig,
  text: string,
  ref: string | undefined,
): Promise<ConcernExtractResult | null> {
  if (!cfg.enabled || !text.trim()) return null;

  const body = {
    jsonrpc: "2.0",
    method: "concern.extract",
    id: `extract-${crypto.randomUUID()}`,
    params: {
      text,
      origin: "user_input",
      ...(ref ? { ref } : {}),
    },
  };

  let res: Response;
  try {
    res = await fetch(cfg.daemonUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120_000),
    });
  } catch (err) {
    throw new Error(
      `OpenCOAT concern.extract failed at ${cfg.daemonUrl}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  if (!res.ok) {
    const textBody = await res.text().catch(() => "");
    throw new Error(`OpenCOAT concern.extract HTTP ${res.status}: ${textBody.slice(0, 200)}`);
  }

  const json = (await res.json()) as {
    result?: ConcernExtractResult;
    error?: { message?: string };
  };
  if (json.error) {
    throw new Error(json.error.message ?? "concern.extract failed");
  }
  return json.result ?? null;
}

export async function submitJoinpoint(
  cfg: BridgeConfig,
  joinpoint: JoinpointWire,
  options?: { extractFromChat?: boolean },
): Promise<ConcernInjection | null> {
  if (!cfg.enabled) return null;

  const body = {
    jsonrpc: "2.0",
    method: "joinpoint.submit",
    id: joinpoint.id,
    params: {
      joinpoint,
      ...(options?.extractFromChat ? { extract_from_chat: true } : {}),
    },
  };

  let res: Response;
  try {
    res = await fetch(cfg.daemonUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
  } catch (err) {
    throw new Error(
      `OpenCOAT daemon unreachable at ${cfg.daemonUrl}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`OpenCOAT daemon HTTP ${res.status}: ${text.slice(0, 200)}`);
  }

  const json = (await res.json()) as {
    result?: ConcernInjection | null;
    error?: { message?: string };
  };

  if (json.error) {
    throw new Error(json.error.message ?? "joinpoint.submit failed");
  }

  return json.result ?? null;
}

export function buildJoinpoint(
  name: string,
  payload: Record<string, unknown>,
  ctx: AgentHookCtx,
  level: number = JOINPOINT_LEVEL_LIFECYCLE,
): JoinpointWire {
  const id = newJoinpointId();
  const session = ctx.sessionId ?? ctx.sessionKey;
  return {
    id,
    level,
    name,
    host: "openclaw",
    agent_session_id: session,
    host_round_id: ctx.runId,
    ts: new Date().toISOString(),
    payload,
  };
}

export function textPayload(...parts: string[]): Record<string, unknown> {
  const text = parts.filter(Boolean).join("\n\n");
  return { text, raw_text: text, content: text };
}
