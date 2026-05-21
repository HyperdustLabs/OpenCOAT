/**
 * Runtime observers for joinpoints not exposed as `api.on` plugin hooks.
 *
 * Sources: `api.runtime.events.onAgentEvent`, `api.registerHook` (session compact),
 * queue depth poll (host `getFollowupQueueDepth`), task registry poll
 * (`api.runtime.tasks.runs.bindSession`). All paths are observe-only submit —
 * see design doc §4.1 / Appendix B.2.
 */
import type { ObserveEmitter } from "./emit-joinpoint.js";
import { loadFollowupQueueDepth } from "./openclaw-internals.js";
import type {
  AgentEventPayload,
  AgentHookCtx,
  BridgeConfig,
  BridgePluginApi,
  TaskRunView,
} from "./types.js";

const TERMINAL_TASK_STATUSES = new Set([
  "succeeded",
  "failed",
  "timed_out",
  "cancelled",
  "lost",
]);

const trackedSessionKeys = new Set<string>();
const queueDepthByKey = new Map<string, number>();
const taskStatusBySession = new Map<string, Map<string, string>>();
const runningRuns = new Set<string>();

export function trackSessionKey(sessionKey: string | undefined): void {
  if (sessionKey?.trim()) trackedSessionKeys.add(sessionKey.trim());
}

export function recordQueueDepthSnapshot(
  sessionKey: string | undefined,
  depth: unknown,
): void {
  if (!sessionKey?.trim() || typeof depth !== "number" || !Number.isFinite(depth)) {
    return;
  }
  trackedSessionKeys.add(sessionKey.trim());
  queueDepthByKey.set(sessionKey.trim(), Math.max(0, Math.floor(depth)));
}

export function agentEventJoinpoint(
  evt: AgentEventPayload,
): { name: string; payload: Record<string, unknown> } | null {
  const data = evt.data ?? {};
  switch (evt.stream) {
    case "lifecycle": {
      const phase = typeof data.phase === "string" ? data.phase : "";
      if (phase === "start") {
        return {
          name: "reply_run.before_begin",
          payload: { phase, run_id: evt.runId, ...data },
        };
      }
      if (phase === "error") {
        return {
          name: "error.detected",
          payload: { phase, run_id: evt.runId, ...data },
        };
      }
      return null;
    }
    case "command_output":
      return {
        name: "command.output_stream",
        payload: { run_id: evt.runId, stream: evt.stream, ...data },
      };
    case "patch":
      return {
        name: "patch.summary_created",
        payload: { run_id: evt.runId, stream: evt.stream, ...data },
      };
    case "plan":
      return {
        name: "planning.plan_updated",
        payload: { run_id: evt.runId, ...data },
      };
    case "compaction": {
      const phase = typeof data.phase === "string" ? data.phase : "";
      if (phase === "start") {
        return {
          name: "before_memory_write",
          payload: { phase, run_id: evt.runId, stream: "compaction", ...data },
        };
      }
      if (phase === "end") {
        return {
          name: "after_memory_write",
          payload: { phase, run_id: evt.runId, stream: "compaction", ...data },
        };
      }
      return null;
    }
    case "approval": {
      const phase = typeof data.phase === "string" ? data.phase : "";
      if (phase === "requested") {
        return {
          name: "approval.requested",
          payload: { run_id: evt.runId, ...data },
        };
      }
      return null;
    }
    default:
      return null;
  }
}

export function agentEventRunningJoinpoint(
  evt: AgentEventPayload,
): { name: string; payload: Record<string, unknown> } | null {
  if (evt.stream === "lifecycle") return null;
  const data = evt.data ?? {};
  if (evt.stream === "item" && data.phase === "start") {
    return {
      name: "reply_run.phase.running",
      payload: { run_id: evt.runId, stream: evt.stream, ...data },
    };
  }
  if (evt.stream === "assistant" || evt.stream === "tool") {
    return {
      name: "reply_run.phase.running",
      payload: { run_id: evt.runId, stream: evt.stream, ...data },
    };
  }
  return null;
}

export function diffQueueDepth(
  sessionKey: string,
  nextDepth: number,
): { name: string; payload: Record<string, unknown> }[] {
  const prev = queueDepthByKey.get(sessionKey) ?? 0;
  queueDepthByKey.set(sessionKey, nextDepth);
  const out: { name: string; payload: Record<string, unknown> }[] = [];
  if (nextDepth > prev) {
    out.push({
      name: "queue.before_enqueue",
      payload: { session_key: sessionKey, depth_before: prev, depth_after: nextDepth },
    });
  }
  if (nextDepth < prev && prev > 0) {
    out.push({
      name: "queue.before_collect",
      payload: { session_key: sessionKey, depth_before: prev, depth_after: nextDepth },
    });
  }
  return out;
}

export function diffTaskSnapshots(
  sessionKey: string,
  tasks: TaskRunView[],
): { name: string; payload: Record<string, unknown> }[] {
  let prev = taskStatusBySession.get(sessionKey);
  if (!prev) {
    prev = new Map();
    taskStatusBySession.set(sessionKey, prev);
  }
  const next = new Map<string, string>();
  const events: { name: string; payload: Record<string, unknown> }[] = [];

  for (const task of tasks) {
    next.set(task.id, task.status);
    const oldStatus = prev.get(task.id);
    if (oldStatus === undefined) {
      events.push({
        name: "task.before_create",
        payload: {
          task_id: task.id,
          status: task.status,
          title: task.title,
          session_key: sessionKey,
        },
      });
      events.push({
        name: "task.after_create",
        payload: {
          task_id: task.id,
          status: task.status,
          title: task.title,
          session_key: sessionKey,
        },
      });
      continue;
    }
    if (
      !TERMINAL_TASK_STATUSES.has(oldStatus) &&
      TERMINAL_TASK_STATUSES.has(task.status)
    ) {
      events.push({
        name: "task.before_terminal",
        payload: {
          task_id: task.id,
          status: task.status,
          previous_status: oldStatus,
          session_key: sessionKey,
        },
      });
    }
  }

  taskStatusBySession.set(sessionKey, next);
  return events;
}

function hookCtxFromAgentEvent(evt: AgentEventPayload): AgentHookCtx {
  return {
    runId: evt.runId,
    sessionKey: evt.sessionKey,
    sessionId: evt.sessionKey,
  };
}

function hookCtxForSession(sessionKey: string): AgentHookCtx {
  return { sessionKey, sessionId: sessionKey };
}

function listTasksForSession(
  api: BridgePluginApi,
  sessionKey: string,
): TaskRunView[] {
  const runs = api.runtime?.tasks?.runs;
  if (!runs?.bindSession) return [];
  try {
    return runs.bindSession({ sessionKey }).list();
  } catch {
    return [];
  }
}

async function pollObservers(
  api: BridgePluginApi,
  cfg: BridgeConfig,
  emitter: ObserveEmitter,
): Promise<void> {
  const queueDepth = loadFollowupQueueDepth();
  for (const sessionKey of trackedSessionKeys) {
    const ctx = hookCtxForSession(sessionKey);

    if (queueDepth) {
      let depth = 0;
      try {
        depth = queueDepth(sessionKey);
      } catch {
        depth = 0;
      }
      for (const { name, payload } of diffQueueDepth(sessionKey, depth)) {
        await emitter.observe(name, payload, ctx, { source: "queue-poll" });
      }
    }

    const tasks = listTasksForSession(api, sessionKey);
    for (const { name, payload } of diffTaskSnapshots(sessionKey, tasks)) {
      await emitter.observe(name, payload, ctx, { source: "task-poll" });
    }
  }
}

export function installRuntimeObservers(
  api: BridgePluginApi,
  cfg: BridgeConfig,
  emitter: ObserveEmitter,
): void {
  if (cfg.runtimeObservers === false) return;

  const onAgentEvent = api.runtime?.events?.onAgentEvent;
  if (onAgentEvent) {
    onAgentEvent((evt) => {
      if (evt.sessionKey) trackSessionKey(evt.sessionKey);

      const mapped = agentEventJoinpoint(evt);
      if (mapped) {
        void emitter.observe(mapped.name, mapped.payload, hookCtxFromAgentEvent(evt), {
          source: `agent-event:${evt.stream}`,
        });
      }

      if (evt.stream === "lifecycle") {
        const phase = typeof evt.data?.phase === "string" ? evt.data.phase : "";
        if (phase === "start") runningRuns.add(evt.runId);
        if (phase === "end" || phase === "error") runningRuns.delete(evt.runId);
        return;
      }

      if (!runningRuns.has(evt.runId)) return;
      const running = agentEventRunningJoinpoint(evt);
      if (!running) return;
      runningRuns.delete(evt.runId);
      void emitter.observe(running.name, running.payload, hookCtxFromAgentEvent(evt), {
        source: `agent-event:${evt.stream}`,
      });
    });
  }

  if (api.registerHook) {
    const compactHandler = async (event: {
      type?: string;
      action?: string;
      sessionKey?: string;
      context?: Record<string, unknown>;
    }) => {
      if (event.type !== "session") return;
      const sessionKey = event.sessionKey;
      if (!sessionKey) return;
      trackSessionKey(sessionKey);
      const ctx = hookCtxForSession(sessionKey);
      const base = { internal_hook: `${event.type}:${event.action}`, ...event.context };
      if (event.action === "compact:before") {
        await emitter.observe("before_memory_write", base, ctx, {
          source: "internal-hook:session:compact:before",
        });
      } else if (event.action === "compact:after") {
        await emitter.observe("after_memory_write", base, ctx, {
          source: "internal-hook:session:compact:after",
        });
      }
    };
    api.registerHook(
      ["session:compact:before", "session:compact:after"],
      compactHandler,
      {
        name: "opencoat-bridge-session-compact",
        description: "Mirror OpenClaw session compaction events into OpenCOAT memory joinpoints.",
      },
    );
  }

  if (!api.registerService) return;

  const pollMs = cfg.observerPollMs ?? 500;
  let timer: ReturnType<typeof setInterval> | undefined;

  api.registerService({
    id: "opencoat-bridge-runtime-observer",
    start: () => {
      void pollObservers(api, cfg, emitter);
      timer = setInterval(() => {
        void pollObservers(api, cfg, emitter);
      }, pollMs);
    },
    stop: () => {
      if (timer) clearInterval(timer);
      timer = undefined;
    },
  });
}
