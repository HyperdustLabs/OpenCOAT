import { createRequire } from "node:module";
import { dirname, join } from "node:path";

export type FollowupQueueDepthFn = (sessionKey: string) => number;

let queueDepthFn: FollowupQueueDepthFn | null | undefined;

/** Load queue depth helper from the host OpenClaw install (stable dist entry). */
export function loadFollowupQueueDepth(): FollowupQueueDepthFn | null {
  if (queueDepthFn !== undefined) return queueDepthFn;
  try {
    const require = createRequire(import.meta.url);
    const pkgJson = require.resolve("openclaw/package.json");
    const mod = require(join(dirname(pkgJson), "dist/status-queue.runtime.js")) as {
      getFollowupQueueDepth?: FollowupQueueDepthFn;
    };
    queueDepthFn =
      typeof mod.getFollowupQueueDepth === "function"
        ? mod.getFollowupQueueDepth
        : null;
  } catch {
    queueDepthFn = null;
  }
  return queueDepthFn;
}

/** Test-only reset. */
export function resetOpenClawInternalsCacheForTest(): void {
  queueDepthFn = undefined;
}
