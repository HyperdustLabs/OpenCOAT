import type { ReflexPolicySpec } from "./reflex-policy-spec.js";

export type BridgeConfig = {
  daemonUrl: string;
  enabled: boolean;
  logActivations: boolean;
  /** Call ``concern.extract`` on user messages before ``joinpoint.submit``. */
  extractOnUserMessage: boolean;
  /** Poll queue depth + task registry via ``api.runtime`` / host internals. */
  runtimeObservers: boolean;
  /** Interval for queue/task poll service (ms). */
  observerPollMs: number;
  /** Run ``before_tool_call`` through in-proc ``ReflexMonitor`` (v0.3 TCB prototype). */
  inProcReflexToolGuard: boolean;
  /** Pull ``reflex.policies.export`` from daemon on plugin load. */
  reflexSyncFromDaemon: boolean;
  /** Emit joinpoint.submit after in-proc guard for DCN audit (async). */
  reflexAuditToDaemon: boolean;
  /** Inline portable policy specs (merged with daemon export). */
  reflexPolicies: ReflexPolicySpec[];
  /** When daemon export is empty, include built-in ``demo-tool-block`` spec. */
  reflexIncludeDemoPolicy: boolean;
  /** Append structured ``r_t`` records via daemon ``credit.r_t.append`` (v0.3 step 3). */
  emitRtJsonl: boolean;
};

export type AgentEventPayload = {
  runId: string;
  seq?: number;
  stream: string;
  ts?: number;
  data: Record<string, unknown>;
  sessionKey?: string;
};

export type TaskRunView = {
  id: string;
  status: string;
  title: string;
  sessionKey: string;
};

export type BridgePluginApi = {
  on: (hook: string, handler: (...args: unknown[]) => unknown) => void;
  logger?: { info?: (msg: string) => void; warn?: (msg: string) => void };
  pluginConfig?: Record<string, unknown>;
  runtime?: {
    events?: {
      onAgentEvent?: (
        listener: (evt: AgentEventPayload) => void,
      ) => () => void;
    };
    tasks?: {
      runs?: {
        bindSession: (params: { sessionKey: string }) => {
          list: () => TaskRunView[];
        };
      };
    };
  };
  registerService?: (service: {
    id: string;
    start: (ctx?: unknown) => void | Promise<void>;
    stop?: () => void | Promise<void>;
  }) => void;
  registerHook?: (
    events: string | string[],
    handler: (event: {
      type?: string;
      action?: string;
      sessionKey?: string;
      context?: Record<string, unknown>;
    }) => void | Promise<void>,
    opts?: { name?: string; description?: string; priority?: number },
  ) => void;
};

export type ConcernExtractResult = {
  candidates: unknown[];
  rejected: { span: string; reason: string }[];
  upserted: boolean;
};

export type ConcernInjection = {
  weave_id: string;
  host_round_id?: string | null;
  agent_session_id?: string | null;
  injections: InjectionRow[];
};

export type InjectionRow = {
  concern_id: string;
  advice_type: string;
  target: string;
  mode: string;
  level?: string;
  content: string;
  priority?: number;
};

export type JoinpointWire = {
  id: string;
  level: number;
  name: string;
  host: string;
  agent_session_id?: string;
  host_round_id?: string;
  /** @deprecated Use host_round_id */
  turn_id?: string;
  ts: string;
  payload: Record<string, unknown>;
};

export type AgentHookCtx = {
  runId?: string;
  sessionId?: string;
  sessionKey?: string;
  agentId?: string;
};
