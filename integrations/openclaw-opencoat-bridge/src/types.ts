export type BridgeConfig = {
  daemonUrl: string;
  enabled: boolean;
  logActivations: boolean;
  /** Call ``concern.extract`` on user messages before ``joinpoint.submit``. */
  extractOnUserMessage: boolean;
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
