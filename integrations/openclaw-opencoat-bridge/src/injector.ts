import type { ConcernInjection, InjectionRow } from "./types.js";

const APPEND_MODES = new Set(["insert", "annotate", "warn", "verify", "defer"]);
const BLOCK_MODES = new Set(["block", "suppress", "escalate"]);

function isRuntimePromptTarget(target: string): boolean {
  return target === "runtime_prompt" || target.startsWith("runtime_prompt.");
}

function isToolTarget(target: string): boolean {
  return target === "tool_call" || target.startsWith("tool_call.");
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
