/** Portable deterministic reflex policy spec (v0.3 §10.4 export from OpenCOAT). */

export type ReflexCriticality = "safety_critical" | "advisory";

export type ReflexPolicySpec = {
  id: string;
  criticality: ReflexCriticality;
  /** Only `tool_call` is implemented in the TCB prototype. */
  action_kind: "tool_call";
  predicate: ReflexPredicateSpec;
  deny_reason: string;
};

export type ReflexPredicateSpec =
  | {
      kind: "args_contains";
      needles: string[];
      case_insensitive?: boolean;
    }
  | {
      kind: "tool_name";
      names: string[];
    };

export type ReflexPolicyExport = {
  version: "0.1";
  policies: ReflexPolicySpec[];
};

export function parseReflexPolicyExport(raw: unknown): ReflexPolicyExport | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (obj.version !== "0.1" || !Array.isArray(obj.policies)) return null;

  const policies: ReflexPolicySpec[] = [];
  for (const row of obj.policies) {
    if (!row || typeof row !== "object") continue;
    const p = row as Record<string, unknown>;
    if (typeof p.id !== "string" || !p.id.trim()) continue;
    if (p.action_kind !== "tool_call") continue;
    if (p.criticality !== "safety_critical" && p.criticality !== "advisory") continue;
    if (typeof p.deny_reason !== "string") continue;

    const pred = p.predicate;
    if (!pred || typeof pred !== "object") continue;
    const pr = pred as Record<string, unknown>;

    let predicate: ReflexPredicateSpec | null = null;
    if (pr.kind === "args_contains" && Array.isArray(pr.needles)) {
      const needles = pr.needles.filter((n): n is string => typeof n === "string" && n.length > 0);
      if (needles.length) {
        predicate = {
          kind: "args_contains",
          needles,
          case_insensitive: pr.case_insensitive === true,
        };
      }
    } else if (pr.kind === "tool_name" && Array.isArray(pr.names)) {
      const names = pr.names.filter((n): n is string => typeof n === "string" && n.length > 0);
      if (names.length) predicate = { kind: "tool_name", names };
    }
    if (!predicate) continue;

    policies.push({
      id: p.id,
      criticality: p.criticality,
      action_kind: "tool_call",
      predicate,
      deny_reason: p.deny_reason,
    });
  }

  return { version: "0.1", policies };
}
