import type { ReflexPolicySpec } from "./reflex-policy-spec.js";
import type { Action, ActionKind, Decision, ReflexPolicy, State } from "./reflex-monitor.js";

function serializeArgs(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args);
  } catch {
    return String(args);
  }
}

function argsContains(
  action: Action,
  needles: string[],
  caseInsensitive: boolean,
): boolean {
  const hay = caseInsensitive
    ? serializeArgs(action.args).toLowerCase()
    : serializeArgs(action.args);
  for (const needle of needles) {
    const n = caseInsensitive ? needle.toLowerCase() : needle;
    if (hay.includes(n)) return true;
  }
  return false;
}

function compileOne(spec: ReflexPolicySpec): ReflexPolicy {
  const deny = (): Decision => ({
    kind: "deny",
    policy_id: spec.id,
    reason: spec.deny_reason,
  });

  const rewrite = (action: Action): Decision => ({
    kind: "rewrite",
    policy_id: spec.id,
    reason: spec.deny_reason,
    action: {
      ...action,
      args: {
        ...action.args,
        content: spec.rewrite_content ?? spec.deny_reason,
      },
    },
  });

  return {
    id: spec.id,
    criticality: spec.criticality,
    applies(action: Action, _state: State): boolean {
      if (action.kind !== spec.action_kind) return false;
      if (spec.predicate.kind === "tool_name") {
        return spec.predicate.names.includes(action.name);
      }
      return argsContains(
        action,
        spec.predicate.needles,
        spec.predicate.case_insensitive === true,
      );
    },
    decide(action: Action, state: State): Decision {
      if (!this.applies(action, state)) return { kind: "allow" };
      if (spec.effect === "rewrite" && spec.rewrite_content) {
        return rewrite(action);
      }
      return deny();
    },
  };
}

export function compileReflexPolicies(specs: ReflexPolicySpec[]): ReflexPolicy[] {
  return specs.map(compileOne);
}

/** Built-in demo policy matching ``demo-tool-block`` when daemon export is unavailable. */
export const DEMO_TOOL_BLOCK_SPEC: ReflexPolicySpec = {
  id: "demo-tool-block",
  criticality: "safety_critical",
  action_kind: "tool_call",
  predicate: {
    kind: "args_contains",
    needles: ["rm -rf", "rm  -rf"],
  },
  deny_reason:
    "Refusing destructive shell command — `rm -rf` is blocked by demo-tool-block.",
};

/** Queue dogfood block when daemon export is unavailable. */
export const DEMO_QUEUE_BLOCK_SPEC: ReflexPolicySpec = {
  id: "oc.dogfood.queue-block",
  criticality: "safety_critical",
  action_kind: "queue_enqueue",
  predicate: {
    kind: "text_contains",
    needles: ["QUEUE_DOGFOOD_BLOCK"],
  },
  deny_reason:
    "Follow-up queue blocked by OpenCOAT dogfood concern (oc.dogfood.queue-block).",
};

export function buildPayloadAction(
  kind: ActionKind,
  payload: Record<string, unknown>,
): Action {
  return {
    kind,
    name: kind,
    args: { ...payload, text: JSON.stringify(payload) },
    raw: payload,
  };
}
