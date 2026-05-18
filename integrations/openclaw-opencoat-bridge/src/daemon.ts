import type { AgentHookCtx, BridgeConfig, ConcernInjection, JoinpointWire } from "./types.js";

const JOINPOINT_LEVEL_LIFECYCLE = 1;

export function resolveConfig(raw: Record<string, unknown> | undefined): BridgeConfig {
  const daemonUrl =
    (typeof raw?.daemonUrl === "string" && raw.daemonUrl.trim()) ||
    "http://127.0.0.1:7878/rpc";
  return {
    daemonUrl,
    enabled: raw?.enabled !== false,
    logActivations: raw?.logActivations === true,
  };
}

export function runKey(ctx: AgentHookCtx): string {
  return ctx.runId ?? ctx.sessionId ?? ctx.sessionKey ?? "default";
}

export function newJoinpointId(): string {
  return `jp-oc-${crypto.randomUUID()}`;
}

export async function submitJoinpoint(
  cfg: BridgeConfig,
  joinpoint: JoinpointWire,
): Promise<ConcernInjection | null> {
  if (!cfg.enabled) return null;

  const body = {
    jsonrpc: "2.0",
    method: "joinpoint.submit",
    id: joinpoint.id,
    params: { joinpoint },
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
): JoinpointWire {
  const id = newJoinpointId();
  const session = ctx.sessionId ?? ctx.sessionKey;
  return {
    id,
    level: JOINPOINT_LEVEL_LIFECYCLE,
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
