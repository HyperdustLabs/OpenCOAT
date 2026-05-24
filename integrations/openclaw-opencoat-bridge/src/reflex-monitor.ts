/**
 * In-proc authoritative reflex monitor (v0.3 §10.2–10.3 TCB prototype).
 *
 * Pure, synchronous, no I/O. Safety-critical policies fail-closed on error.
 */

import type { ReflexCriticality } from "./reflex-policy-spec.js";

export type ActionKind =
  | "tool_call"
  | "spawn"
  | "message_out"
  | "queue_enqueue"
  | "memory_write"
  | "tool_result_persist";

export type Action = {
  kind: ActionKind;
  name: string;
  args: Record<string, unknown>;
  raw?: unknown;
};

export type State = {
  session_id: string;
  turn_id: string;
  features: Record<string, unknown>;
};

export type AllowDecision = { kind: "allow" };
export type DenyDecision = {
  kind: "deny";
  reason: string;
  policy_id: string;
};
export type RewriteDecision = {
  kind: "rewrite";
  action: Action;
  reason: string;
  policy_id: string;
};

export type Decision = AllowDecision | DenyDecision | RewriteDecision;

export type DecisionRecord = {
  turn_id: string;
  action_kind: ActionKind;
  action_name: string;
  decision: Decision["kind"];
  policy_id?: string;
  reason?: string;
  criticality?: ReflexCriticality;
};

export type ReflexPolicy = {
  id: string;
  criticality: ReflexCriticality;
  applies: (action: Action, state: State) => boolean;
  decide: (action: Action, state: State) => Decision;
};

const DECISION_RANK: Record<Decision["kind"], number> = {
  deny: 3,
  rewrite: 2,
  allow: 1,
};

function mergeDecisions(current: Decision, next: Decision): Decision {
  const curRank = DECISION_RANK[current.kind];
  const nextRank = DECISION_RANK[next.kind];
  if (nextRank > curRank) return next;
  if (nextRank < curRank) return current;
  if (current.kind === "deny" && next.kind === "deny") {
    return {
      kind: "deny",
      policy_id: current.policy_id,
      reason: [current.reason, next.reason].filter(Boolean).join("\n"),
    };
  }
  if (current.kind === "rewrite" && next.kind === "rewrite") {
    if (current.policy_id <= next.policy_id) return current;
    return next;
  }
  return current;
}

export class ReflexMonitor {
  private readonly policies: ReflexPolicy[];
  private readonly conservedCore: ReadonlySet<string>;

  constructor(
    policies: ReflexPolicy[],
    options?: { conservedCore?: Iterable<string> },
  ) {
    this.policies = [...policies].sort((a, b) => a.id.localeCompare(b.id));
    this.conservedCore = new Set(options?.conservedCore ?? []);
  }

  conservedCoreIds(): ReadonlySet<string> {
    return this.conservedCore;
  }

  mediate(action: Action, state: State): { decision: Decision; record: DecisionRecord } {
    let decision: Decision = { kind: "allow" };
    let winningPolicy: ReflexPolicy | undefined;
    let matchedPolicyId: string | undefined;

    for (const policy of this.policies) {
      try {
        if (!policy.applies(action, state)) continue;
        const next = policy.decide(action, state);
        if (next.kind === "allow") continue;
        matchedPolicyId = policy.id;
        decision = winningPolicy
          ? mergeDecisions(decision, next)
          : next;
        if (!winningPolicy || DECISION_RANK[next.kind] >= DECISION_RANK[decision.kind]) {
          winningPolicy = policy;
        }
      } catch (err) {
        if (policy.criticality === "safety_critical") {
          const reason =
            err instanceof Error ? err.message : "Reflex policy evaluation failed";
          return {
            decision: {
              kind: "deny",
              policy_id: policy.id,
              reason: `ReflexMonitor fail-closed: ${reason}`,
            },
            record: {
              turn_id: state.turn_id,
              action_kind: action.kind,
              action_name: action.name,
              decision: "deny",
              policy_id: policy.id,
              reason,
              criticality: policy.criticality,
            },
          };
        }
      }
    }

    const record: DecisionRecord = {
      turn_id: state.turn_id,
      action_kind: action.kind,
      action_name: action.name,
      decision: decision.kind,
      policy_id:
        decision.kind === "allow"
          ? matchedPolicyId
          : decision.policy_id ?? matchedPolicyId,
      reason: decision.kind === "allow" ? undefined : decision.reason,
      criticality: winningPolicy?.criticality,
    };

    return { decision, record };
  }
}
