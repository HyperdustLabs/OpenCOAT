import { buildJoinpoint, submitJoinpoint } from "./daemon.js";
import type { AgentHookCtx, BridgeConfig, ConcernInjection } from "./types.js";

export type ObserveEmitter = {
  observe: (
    joinpointName: string,
    payload: Record<string, unknown>,
    ctx: AgentHookCtx,
    options?: { level?: number; source?: string },
  ) => Promise<ConcernInjection | null>;
};

type Logger = { info?: (msg: string) => void; warn?: (msg: string) => void };

export function createObserveEmitter(
  cfg: BridgeConfig,
  logger?: Logger,
): ObserveEmitter {
  return {
    async observe(joinpointName, payload, ctx, options) {
      if (!cfg.enabled) return null;
      try {
        const jp = buildJoinpoint(
          joinpointName,
          {
            ...payload,
            ...(options?.source ? { observer_source: options.source } : {}),
          },
          ctx,
          options?.level,
        );
        const inj = await submitJoinpoint(cfg, jp);
        if (cfg.logActivations && inj?.injections?.length) {
          const ids = inj.injections.map((r) => r.concern_id).join(", ");
          logger?.info?.(
            `[opencoat-bridge] ${options?.source ?? "observe"}→${joinpointName}: ${ids}`,
          );
        }
        return inj;
      } catch (err) {
        logger?.warn?.(
          `[opencoat-bridge] ${options?.source ?? "observe"}→${joinpointName}: ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
        return null;
      }
    },
  };
}
