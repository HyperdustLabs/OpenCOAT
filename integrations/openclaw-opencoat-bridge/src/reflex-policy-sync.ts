import {
  parseReflexPolicyExport,
  type ReflexPolicyExport,
} from "./reflex-policy-spec.js";
import { compileReflexPolicies, DEMO_TOOL_BLOCK_SPEC, DEMO_QUEUE_BLOCK_SPEC } from "./reflex-policies.js";
import { ReflexMonitor } from "./reflex-monitor.js";
import type { BridgeConfig } from "./types.js";

export type ReflexRuntime = {
  monitor: ReflexMonitor;
  exportVersion: string;
  policyIds: string[];
};

export async function fetchReflexPolicyExport(
  cfg: BridgeConfig,
): Promise<ReflexPolicyExport | null> {
  if (!cfg.enabled) return null;

  const body = {
    jsonrpc: "2.0",
    method: "reflex.policies.export",
    id: `reflex-export-${crypto.randomUUID()}`,
    params: { action_kind: "all" },
  };

  let res: Response;
  try {
    res = await fetch(cfg.daemonUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    return null;
  }

  if (!res.ok) return null;

  const json = (await res.json()) as {
    result?: unknown;
    error?: { message?: string };
  };
  if (json.error) return null;
  return parseReflexPolicyExport(json.result);
}

export function inProcReflexEnabled(cfg: BridgeConfig): boolean {
  return cfg.inProcReflexToolGuard || cfg.inProcReflexGuards;
}

export function buildReflexRuntime(
  cfg: BridgeConfig,
  exported: ReflexPolicyExport | null,
): ReflexRuntime {
  const specs = [
  ...(cfg.reflexPolicies ?? []),
  ...(exported?.policies ?? []),
  ...(cfg.reflexIncludeDemoPolicy && !exported?.policies?.length
    ? [DEMO_TOOL_BLOCK_SPEC, DEMO_QUEUE_BLOCK_SPEC]
    : []),
  ];

  const byId = new Map<string, (typeof specs)[number]>();
  for (const spec of specs) {
    byId.set(spec.id, spec);
  }
  const unique = [...byId.values()];
  const policies = compileReflexPolicies(unique);

  return {
    monitor: new ReflexMonitor(policies, {
      conservedCore: unique
        .filter((s) => s.criticality === "safety_critical")
        .map((s) => s.id),
    }),
    exportVersion: exported?.version ?? "inline",
    policyIds: unique.map((s) => s.id),
  };
}

export async function loadReflexRuntime(cfg: BridgeConfig): Promise<ReflexRuntime> {
  const exported =
    inProcReflexEnabled(cfg) && cfg.reflexSyncFromDaemon
      ? await fetchReflexPolicyExport(cfg)
      : null;
  return buildReflexRuntime(cfg, exported);
}
