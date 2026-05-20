import type { ConcernInjection, InjectionRow } from "./types.js";

const APPEND_MODES = new Set(["insert", "annotate", "warn", "verify", "defer"]);
const BLOCK_MODES = new Set(["block", "suppress", "escalate"]);

function isRuntimePromptTarget(target: string): boolean {
  return target === "runtime_prompt" || target.startsWith("runtime_prompt.");
}

function isToolTarget(target: string): boolean {
  return target === "tool_call" || target.startsWith("tool_call.");
}

function isQueueTarget(target: string): boolean {
  return target === "queue" || target.startsWith("queue.");
}

/** Fold prompt-level INSERT (etc.) rows into OpenClaw prependSystemContext. */
export function foldPromptInjection(injection: ConcernInjection | null): string {
  if (!injection?.injections?.length) return "";

  const chunks: string[] = [];
  const seen = new Set<string>();

  for (const row of injection.injections) {
    if (!isRuntimePromptTarget(row.target)) continue;
    if (!APPEND_MODES.has(row.mode) && !BLOCK_MODES.has(row.mode)) continue;
    const key = `${row.concern_id}\n${row.content}`;
    if (seen.has(key)) continue;
    seen.add(key);
    chunks.push(
      `[OpenCOAT · ${row.concern_id} · ${row.advice_type}]\n${row.content.trim()}`,
    );
  }

  if (!chunks.length) return "";
  return `\n\n<OpenCOAT>\n${chunks.join("\n\n")}\n</OpenCOAT>\n`;
}

export type ToolGuardDecision = {
  block: boolean;
  blockReason?: string;
  params?: Record<string, unknown>;
};

/** Interpret tool_guard / BLOCK rows for before_tool_call. */
export function guardToolCall(
  injection: ConcernInjection | null,
  params: Record<string, unknown>,
): ToolGuardDecision {
  if (!injection?.injections?.length) {
    return { block: false, params };
  }

  const reasons: string[] = [];
  let blocked = false;
  let outParams = { ...params };

  for (const row of injection.injections) {
    if (!isToolTarget(row.target)) continue;

    if (BLOCK_MODES.has(row.mode) || row.advice_type === "tool_guard") {
      if (BLOCK_MODES.has(row.mode) || row.mode === "block") {
        blocked = true;
        if (row.content.trim()) reasons.push(row.content.trim());
      }
    }

    if (row.target.startsWith("tool_call.arguments")) {
      if (APPEND_MODES.has(row.mode) && row.content.trim()) {
        // Notes only — do not overwrite structured params on append advice.
        continue;
      }
    }
  }

  return {
    block: blocked,
    blockReason: reasons.length ? reasons.join("\n") : undefined,
    params: outParams,
  };
}

/** Any BLOCK / suppress / escalate row in the injection. */
export function hasBlockingAdvice(injection: ConcernInjection | null): boolean {
  if (!injection?.injections?.length) return false;
  return injection.injections.some(
    (row) =>
      BLOCK_MODES.has(row.mode) ||
      (row.advice_type === "tool_guard" && row.mode === "block"),
  );
}

export function blockReasonFromInjection(
  injection: ConcernInjection | null,
): string | undefined {
  if (!injection?.injections?.length) return undefined;
  const reasons: string[] = [];
  for (const row of injection.injections) {
    if (!BLOCK_MODES.has(row.mode) && row.mode !== "block") continue;
    if (row.content.trim()) reasons.push(row.content.trim());
  }
  return reasons.length ? reasons.join("\n") : undefined;
}

/** Outbound message hook: cancel send when response-level BLOCK advice is present. */
export function messageSendingDecision(
  injection: ConcernInjection | null,
): { cancel?: boolean; content?: string } {
  if (!hasBlockingAdvice(injection)) return {};
  const block = foldPromptInjection(injection);
  const reason = blockReasonFromInjection(injection);
  return {
    cancel: true,
    content: reason ?? "Blocked by OpenCOAT concern.",
  };
}

/** Subagent spawn veto when task-scoped or global BLOCK advice matches. */
export function subagentSpawnDecision(
  injection: ConcernInjection | null,
): { status: "ok" } | { status: "error"; error: string } {
  if (!hasBlockingAdvice(injection)) return { status: "ok" };
  const reason =
    blockReasonFromInjection(injection) ??
    "Blocked by OpenCOAT concern (subagent spawn).";
  return { status: "error", error: reason };
}

export type QueueBeforeEnqueueDecision = {
  block?: boolean;
  blockReason?: string;
  prompt?: string;
  summaryLine?: string;
};

/** Interpret queue-scoped advice for OpenClaw queue_before_enqueue. */
export function queueBeforeEnqueueDecision(
  injection: ConcernInjection | null,
): QueueBeforeEnqueueDecision {
  if (!injection?.injections?.length) return {};

  const reasons: string[] = [];
  const decision: QueueBeforeEnqueueDecision = {};

  for (const row of injection.injections) {
    if (!isQueueTarget(row.target) && !BLOCK_MODES.has(row.mode)) continue;

    if (BLOCK_MODES.has(row.mode)) {
      decision.block = true;
      if (row.content.trim()) reasons.push(row.content.trim());
      continue;
    }

    if (!row.content.trim()) continue;
    if (row.target === "queue.prompt" && row.mode === "rewrite") {
      decision.prompt = row.content.trim();
    } else if (
      (row.target === "queue.summary_line" || row.target === "queue.summaryLine") &&
      row.mode === "rewrite"
    ) {
      decision.summaryLine = row.content.trim();
    }
  }

  if (reasons.length) {
    decision.blockReason = reasons.join("\n");
  }
  return decision;
}

export function mergeInjections(
  ...injections: Array<ConcernInjection | null>
): ConcernInjection | null {
  const rows: InjectionRow[] = [];
  let turnId = "";
  let session: string | null | undefined;

  for (const inj of injections) {
    if (!inj?.injections?.length) continue;
    turnId = inj.weave_id || turnId;
    session = inj.agent_session_id ?? session;
    rows.push(...inj.injections);
  }

  if (!rows.length) return null;
  return {
    weave_id: turnId,
    agent_session_id: session,
    injections: rows,
  };
}
