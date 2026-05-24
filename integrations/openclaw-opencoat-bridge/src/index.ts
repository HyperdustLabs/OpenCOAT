/**
 * OpenCOAT ↔ OpenClaw bridge (daemon-backed).
 *
 * - Plugin hooks (`api.on`): 29 async-safe hooks — see hook-bindings.ts.
 * - Runtime observers: `onAgentEvent`, internal compact hooks, queue/task poll —
 *   see runtime-observers.ts (ADR-0011 MVP queue/reply_run/task observe paths).
 *
 * Full map: README.md and docs/design/opencoat-openclaw-joinpoint-model-v0.1.md §4.1.
 */

import {
  buildJoinpoint,
  resolveConfig,
  runKey,
  submitJoinpoint,
  textPayload,
} from "./daemon.js";
import { HOOK_BINDINGS, SKIPPED_HOOKS } from "./hook-bindings.js";
import {
  foldPromptInjection,
  guardToolCall,
  mergeInjections,
  messageSendingDecision,
  queueBeforeEnqueueDecision,
  subagentSpawnDecision,
} from "./injector.js";
import { promptPayload } from "./messages.js";
import {
  compactionPayload,
  llmPayload,
  passThroughPayload,
  queuePayload,
  subagentPayload,
  toolCallPayload,
  toolResultPayload,
} from "./payloads.js";
import { createObserveEmitter } from "./emit-joinpoint.js";
import { loadReflexRuntime, buildReflexRuntime } from "./reflex-policy-sync.js";
import type { ReflexRuntime } from "./reflex-policy-sync.js";
import type { DecisionRecord } from "./reflex-monitor.js";
import {
  appendRtRecordFireAndForget,
  buildLlmOutputRt,
  buildToolBlockedRt,
  buildToolOutcomeRt,
  buildTurnCompleteRt,
} from "./r-t-emit.js";
import {
  buildReflexState,
  buildToolCallAction,
  failClosedToolGuard,
  reflexToolGuardDecision,
} from "./reflex-tool-guard.js";
import {
  installRuntimeObservers,
  recordQueueDepthSnapshot,
  trackSessionKey,
} from "./runtime-observers.js";
import type {
  AgentHookCtx,
  BridgeConfig,
  BridgePluginApi,
  ConcernInjection,
} from "./types.js";

const pendingByRun = new Map<string, ConcernInjection | null>();
const reflexState: { runtime: ReflexRuntime | null } = { runtime: null };
const lastReflexByRunTool = new Map<string, DecisionRecord>();

function reflexToolKey(run: string, toolName: string): string {
  return `${run}:${toolName}`;
}

function auditToolGuardJoinpoint(
  cfg: BridgeConfig,
  api: BridgePluginApi,
  binding: (typeof HOOK_BINDINGS)[number],
  payload: Record<string, unknown>,
  c: AgentHookCtx,
  block: boolean,
  reason?: string,
): void {
  if (!cfg.reflexAuditToDaemon || !cfg.enabled) return;
  void emit(cfg, api, binding.hook, binding.joinpoint, {
    ...payload,
    reflex_monitor: { block, reason },
  }, c).catch(() => undefined);
}

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
  api: BridgePluginApi,
  cfg: BridgeConfig,
  hook: string,
  joinpointName: string,
  inj: ConcernInjection | null,
): void {
  if (!cfg.logActivations || !inj?.injections?.length) return;
  const ids = inj.injections.map((r) => r.concern_id).join(", ");
  api.logger?.info?.(`[opencoat-bridge] ${hook}→${joinpointName}: ${ids}`);
}

async function emit(
  cfg: BridgeConfig,
  api: BridgePluginApi,
  hook: string,
  joinpointName: string,
  payload: Record<string, unknown>,
  ctx: AgentHookCtx,
  options?: { extractFromChat?: boolean; level?: number },
): Promise<ConcernInjection | null> {
  const jp = buildJoinpoint(joinpointName, payload, ctx, options?.level);
  const inj = await submitJoinpoint(cfg, jp, options);
  logActivation(api, cfg, hook, joinpointName, inj);
  return inj;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function asCtx(value: unknown): AgentHookCtx {
  return (value ?? {}) as AgentHookCtx;
}

function buildPayloadForHook(
  hook: string,
  event: unknown,
): Record<string, unknown> {
  const e = asRecord(event);

  switch (hook) {
    case "message_received": {
      const content = typeof e.content === "string" ? e.content : "";
      return promptPayload({
        parts: [content],
        messages: [{ role: "user", content }],
      });
    }
    case "before_prompt_build": {
      const prompt = typeof e.prompt === "string" ? e.prompt : "";
      const messages = Array.isArray(e.messages) ? e.messages : undefined;
      return promptPayload({ parts: prompt ? [prompt] : [], messages });
    }
    case "before_tool_call":
      return toolCallPayload({
        toolName: typeof e.toolName === "string" ? e.toolName : "tool",
        params:
          e.params && typeof e.params === "object"
            ? (e.params as Record<string, unknown>)
            : {},
      });
    case "after_tool_call":
      return toolResultPayload({
        toolName: typeof e.toolName === "string" ? e.toolName : "tool",
        params:
          e.params && typeof e.params === "object"
            ? (e.params as Record<string, unknown>)
            : {},
        result: e.result,
        error: typeof e.error === "string" ? e.error : undefined,
        durationMs: typeof e.durationMs === "number" ? e.durationMs : undefined,
      });
    case "queue_before_enqueue":
      return queuePayload(e, "before_enqueue");
    case "queue_after_enqueue":
      return queuePayload(e, "after_enqueue");
    case "message_sending": {
      const content = typeof e.content === "string" ? e.content : "";
      return promptPayload({
        parts: [content],
        messages: content ? [{ role: "user", content }] : [],
      });
    }
    case "before_compaction":
      return compactionPayload(e, "before");
    case "after_compaction":
      return compactionPayload(e, "after");
    case "llm_input":
      return llmPayload(e, "input");
    case "llm_output":
      return llmPayload(e, "output");
    case "subagent_spawning":
    case "subagent_delivery_target":
    case "subagent_spawned":
    case "subagent_ended":
      return subagentPayload(e, hook);
    case "session_start":
      return textPayload("session_start");
    case "session_end":
      return textPayload("session_end");
    case "gateway_start":
      return { ...textPayload("gateway_start"), scope: "gateway" };
    case "gateway_stop":
      return { ...textPayload("gateway_stop"), scope: "gateway" };
    case "before_reset":
      return { ...textPayload("session_reset"), stage: "before_reset" };
    default:
      return passThroughPayload(e, { openclaw_hook: hook });
  }
}

async function handleHook(
  api: BridgePluginApi,
  cfg: BridgeConfig,
  binding: (typeof HOOK_BINDINGS)[number],
  event: unknown,
  ctx: unknown,
): Promise<unknown> {
  const c = asCtx(ctx);
  trackSessionKey(c.sessionKey);
  const run = runKey(c);
  const payload = buildPayloadForHook(binding.hook, event);

  try {
    switch (binding.kind) {
      case "buffer_input": {
        const ev = asRecord(event);
        const content = typeof ev.content === "string" ? ev.content : "";
        if (!content.trim()) return;
        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c, {
          extractFromChat: cfg.extractOnUserMessage,
        });
        rememberInjection(run, inj);
        return;
      }

      case "prompt_fold": {
        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c);
        rememberInjection(run, inj);
        const merged = mergeInjections(takePending(run), inj);
        const block = foldPromptInjection(merged);
        if (!block) return {};
        return {
          prependSystemContext: block,
          prependContext: block,
        };
      }

      case "tool_guard": {
        const e = asRecord(event);
        const params =
          e.params && typeof e.params === "object"
            ? { ...(e.params as Record<string, unknown>) }
            : {};
        const toolName = typeof e.toolName === "string" ? e.toolName : "tool";

        if (cfg.inProcReflexToolGuard) {
          const runtime = reflexState.runtime;
          if (!runtime) {
            return failClosedToolGuard(
              params,
              new Error("ReflexMonitor not initialized"),
            );
          }
          try {
            const action = buildToolCallAction({ toolName, params });
            const decision = reflexToolGuardDecision(
              runtime.monitor,
              action,
              buildReflexState(c),
              params,
            );
            auditToolGuardJoinpoint(
              cfg,
              api,
              binding,
              payload,
              c,
              decision.block,
              decision.blockReason,
            );
            if (decision.block) {
              appendRtRecordFireAndForget(
                cfg,
                buildToolBlockedRt(
                  binding.hook,
                  binding.joinpoint,
                  c,
                  toolName,
                  decision.record,
                  decision.blockReason,
                ),
              );
              return {
                block: true,
                blockReason:
                  decision.blockReason ??
                  "Blocked by OpenCOAT ReflexMonitor (tool_guard).",
                params: decision.params,
              };
            }
            if (decision.record) {
              lastReflexByRunTool.set(
                reflexToolKey(run, toolName),
                decision.record,
              );
            }
            return decision.params !== params ? { params: decision.params } : {};
          } catch (err) {
            return failClosedToolGuard(params, err);
          }
        }

        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c);
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
      }

      case "message_out": {
        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c);
        return messageSendingDecision(inj);
      }

      case "subagent_spawn": {
        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c);
        const decision = subagentSpawnDecision(inj);
        if (decision.status === "error") return decision;
        return { status: "ok" };
      }

      case "queue_guard": {
        const inj = await emit(cfg, api, binding.hook, binding.joinpoint, payload, c);
        return queueBeforeEnqueueDecision(inj);
      }

      case "observe":
      default: {
        if (binding.hook === "queue_after_enqueue") {
          const ev = asRecord(event);
          const sessionKey =
            typeof ev.sessionKey === "string" ? ev.sessionKey : c.sessionKey;
          recordQueueDepthSnapshot(sessionKey, ev.depthAfter);
        }
        const level =
          binding.hook === "gateway_start" || binding.hook === "gateway_stop"
            ? 0
            : undefined;
        await emit(cfg, api, binding.hook, binding.joinpoint, payload, c, {
          level,
        });
        if (cfg.emitRtJsonl) {
          const ev = asRecord(event);
          if (binding.hook === "after_tool_call") {
            const toolName =
              typeof ev.toolName === "string" ? ev.toolName : "tool";
            const key = reflexToolKey(run, toolName);
            const reflex = lastReflexByRunTool.get(key);
            lastReflexByRunTool.delete(key);
            appendRtRecordFireAndForget(
              cfg,
              buildToolOutcomeRt(
                binding.hook,
                binding.joinpoint,
                c,
                ev,
                reflex,
              ),
            );
          } else if (binding.hook === "llm_output") {
            appendRtRecordFireAndForget(
              cfg,
              buildLlmOutputRt(binding.hook, binding.joinpoint, c, ev),
            );
          } else if (binding.hook === "agent_end") {
            appendRtRecordFireAndForget(
              cfg,
              buildTurnCompleteRt(binding.hook, binding.joinpoint, c, ev),
            );
          }
        }
        return;
      }
    }
  } catch (err) {
    api.logger?.warn?.(
      `[opencoat-bridge] ${binding.hook}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return binding.kind === "tool_guard"
      ? cfg.inProcReflexToolGuard
        ? failClosedToolGuard(
            {},
            err instanceof Error ? err : new Error(String(err)),
          )
        : {}
      : undefined;
  }
}

export default function register(api: BridgePluginApi): void {
  const cfg = resolveConfig(api.pluginConfig);

  if (cfg.inProcReflexToolGuard) {
    reflexState.runtime = buildReflexRuntime(cfg, null);
    void loadReflexRuntime(cfg)
      .then((runtime) => {
        reflexState.runtime = runtime;
        api.logger?.info?.(
          `[opencoat-bridge] in-proc ReflexMonitor tool_guard policies: ${
            runtime.policyIds.join(", ") || "(none)"
          }`,
        );
      })
      .catch((err) => {
        api.logger?.warn?.(
          `[opencoat-bridge] reflex policy sync failed: ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
      });
  }

  for (const binding of HOOK_BINDINGS) {
    api.on(binding.hook, (event: unknown, ctx: unknown) =>
      handleHook(api, cfg, binding, event, ctx),
    );
  }

  if (cfg.runtimeObservers) {
    installRuntimeObservers(api, cfg, createObserveEmitter(cfg, api.logger));
  }

  const observerNote = cfg.runtimeObservers
    ? "; runtime observers on (agent events + queue/task poll)"
    : "";
  api.logger?.info?.(
    `[opencoat-bridge] registered ${HOOK_BINDINGS.length} hooks ` +
      `(skipped: ${SKIPPED_HOOKS.join(", ")}; daemon=${
        cfg.enabled ? cfg.daemonUrl : "disabled"
      }${observerNote}${
        cfg.inProcReflexToolGuard ? "; in-proc ReflexMonitor tool_guard" : ""
      }${cfg.emitRtJsonl ? "; r_t JSONL emit" : ""})`,
  );
}
