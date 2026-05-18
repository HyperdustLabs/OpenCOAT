/**
 * OpenCOAT ↔ OpenClaw bridge (daemon-backed).
 *
 * Maps real OpenClaw plugin hooks to OpenCOAT joinpoints and calls
 * `joinpoint.submit` on the running daemon. Prompt advice is folded via
 * `prependSystemContext`; tool_guard BLOCK rows surface as
 * `{ block: true, blockReason }` on `before_tool_call`.
 *
 * Hook → joinpoint mapping (v0.2 §4.7.1 analogue):
 *   message_received     → on_user_input   (+ messages[] for COPR discovery)
 *   before_prompt_build  → before_response (+ messages[] from the hook)
 *   before_tool_call     → before_tool_call
 *   session_start        → runtime_start
 */

import {
  buildJoinpoint,
  resolveConfig,
  runKey,
  submitJoinpoint,
  textPayload,
} from "./daemon.js";
import { promptPayload } from "./messages.js";
import { foldPromptInjection, guardToolCall, mergeInjections } from "./injector.js";
import type { AgentHookCtx, BridgeConfig, ConcernInjection } from "./types.js";

type PluginApi = {
  on: (hook: string, handler: (...args: unknown[]) => unknown) => void;
  logger?: { info?: (msg: string) => void; warn?: (msg: string) => void };
  pluginConfig?: Record<string, unknown>;
};

/** Buffered injections between hooks in the same agent run. */
const pendingByRun = new Map<string, ConcernInjection | null>();

function rememberInjection(run: string, inj: ConcernInjection | null): void {
  if (!inj?.injections?.length) return;
  const prev = pendingByRun.get(run);
  pendingByRun.set(run, mergeInjections(prev ?? null, inj));
}

function takePending(run: string): ConcernInjection | null {
  const merged = pendingByRun.get(run) ?? null;
  pendingByRun.delete(run);
  return merged;
}

function logActivation(
  api: PluginApi,
  cfg: BridgeConfig,
  joinpointName: string,
  inj: ConcernInjection | null,
): void {
  if (!cfg.logActivations || !inj?.injections?.length) return;
  const ids = inj.injections.map((r) => r.concern_id).join(", ");
  api.logger?.info?.(`[opencoat-bridge] ${joinpointName}: ${ids}`);
}

async function emit(
  cfg: BridgeConfig,
  api: PluginApi,
  joinpointName: string,
  payload: Record<string, unknown>,
  ctx: AgentHookCtx,
): Promise<ConcernInjection | null> {
  const jp = buildJoinpoint(joinpointName, payload, ctx);
  const inj = await submitJoinpoint(cfg, jp);
  logActivation(api, cfg, joinpointName, inj);
  return inj;
}

export default function register(api: PluginApi): void {
  const cfg = resolveConfig(api.pluginConfig);

  api.on("message_received", async (event: unknown, ctx: unknown) => {
    const e = event as { content?: string };
    const c = ctx as AgentHookCtx;
    const content = typeof e?.content === "string" ? e.content : "";
    if (!content.trim()) return;

    try {
      const inj = await emit(
        cfg,
        api,
        "on_user_input",
        promptPayload({
          parts: [content],
          messages: [{ role: "user", content }],
        }),
        c,
      );
      rememberInjection(runKey(c), inj);
    } catch (err) {
      api.logger?.warn?.(
        `[opencoat-bridge] message_received: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  });

  api.on("before_prompt_build", async (event: unknown, ctx: unknown) => {
    const e = event as { prompt?: string; messages?: unknown[] };
    const c = ctx as AgentHookCtx;
    const run = runKey(c);

    const prompt = typeof e?.prompt === "string" ? e.prompt : "";
    const messages = Array.isArray(e?.messages) ? e.messages : undefined;
    const payload = promptPayload({
      parts: prompt ? [prompt] : [],
      messages,
    });

    try {
      const inj = await emit(cfg, api, "before_response", payload, c);
      rememberInjection(run, inj);
      const merged = mergeInjections(takePending(run), inj);
      const block = foldPromptInjection(merged);
      if (!block) return {};
      return {
        prependSystemContext: block,
        prependContext: block,
      };
    } catch (err) {
      api.logger?.warn?.(
        `[opencoat-bridge] before_prompt_build: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
      return {};
    }
  });

  api.on("before_tool_call", async (event: unknown, ctx: unknown) => {
    const e = event as {
      toolName?: string;
      params?: Record<string, unknown>;
    };
    const c = ctx as AgentHookCtx;
    const toolName = typeof e?.toolName === "string" ? e.toolName : "tool";
    const params =
      e?.params && typeof e.params === "object" ? { ...e.params } : {};

    const argText = JSON.stringify({ name: toolName, arguments: params });
    try {
      const inj = await emit(
        cfg,
        api,
        "before_tool_call",
        textPayload(argText, toolName),
        c,
      );
      const decision = guardToolCall(inj, params);
      if (!decision.block) {
        return decision.params !== params ? { params: decision.params } : {};
      }
      return {
        block: true,
        blockReason:
          decision.blockReason ??
          "Blocked by OpenCOAT concern (tool_guard).",
        params: decision.params,
      };
    } catch (err) {
      api.logger?.warn?.(
        `[opencoat-bridge] before_tool_call: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
      return {};
    }
  });

  api.on("session_start", async (_event: unknown, ctx: unknown) => {
    const c = ctx as AgentHookCtx;
    try {
      await emit(cfg, api, "runtime_start", textPayload("session_start"), c);
    } catch (err) {
      api.logger?.warn?.(
        `[opencoat-bridge] session_start: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  });

  api.logger?.info?.(
    `[opencoat-bridge] registered (daemon=${cfg.enabled ? cfg.daemonUrl : "disabled"})`,
  );
}
