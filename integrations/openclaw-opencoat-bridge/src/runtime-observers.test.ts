import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  agentEventJoinpoint,
  agentEventRunningJoinpoint,
  diffQueueDepth,
  diffTaskSnapshots,
  installRuntimeObservers,
  recordQueueDepthSnapshot,
} from "./runtime-observers.js";
import type { BridgeConfig, BridgePluginApi } from "./types.js";

describe("agentEventJoinpoint", () => {
  it("maps lifecycle start to reply_run.before_begin", () => {
    const mapped = agentEventJoinpoint({
      runId: "r1",
      stream: "lifecycle",
      data: { phase: "start", startedAt: 1 },
    });
    assert.equal(mapped?.name, "reply_run.before_begin");
  });

  it("maps plan stream to planning.plan_updated", () => {
    const mapped = agentEventJoinpoint({
      runId: "r1",
      stream: "plan",
      data: { phase: "update", title: "Plan" },
    });
    assert.equal(mapped?.name, "planning.plan_updated");
  });

  it("maps lifecycle error to error.detected", () => {
    const mapped = agentEventJoinpoint({
      runId: "r1",
      stream: "lifecycle",
      data: { phase: "error", error: "boom" },
    });
    assert.equal(mapped?.name, "error.detected");
  });

  it("maps command_output stream to command.output_stream", () => {
    const mapped = agentEventJoinpoint({
      runId: "r1",
      stream: "command_output",
      data: { phase: "delta", output: "line 1" },
    });
    assert.equal(mapped?.name, "command.output_stream");
  });

  it("maps patch stream to patch.summary_created", () => {
    const mapped = agentEventJoinpoint({
      runId: "r1",
      stream: "patch",
      data: { phase: "end", summary: "2 files changed" },
    });
    assert.equal(mapped?.name, "patch.summary_created");
  });
});

describe("agentEventRunningJoinpoint", () => {
  it("maps assistant stream while run is active", () => {
    const mapped = agentEventRunningJoinpoint({
      runId: "r1",
      stream: "assistant",
      data: { text: "hi" },
    });
    assert.equal(mapped?.name, "reply_run.phase.running");
  });
});

describe("diffQueueDepth", () => {
  it("emits before_enqueue when depth increases", () => {
    const key = `sess-${Math.random()}`;
    diffQueueDepth(key, 0);
    const events = diffQueueDepth(key, 2);
    assert.deepEqual(
      events.map((e) => e.name),
      ["queue.before_enqueue"],
    );
  });

  it("emits before_collect when depth decreases from positive", () => {
    const key = `sess-${Math.random()}`;
    diffQueueDepth(key, 2);
    const events = diffQueueDepth(key, 0);
    assert.deepEqual(
      events.map((e) => e.name),
      ["queue.before_collect"],
    );
  });

  it("uses native queue hook snapshots as the next poll baseline", () => {
    const key = `sess-${Math.random()}`;
    recordQueueDepthSnapshot(key, 2);
    const events = diffQueueDepth(key, 2);
    assert.deepEqual(events, []);
  });
});

describe("diffTaskSnapshots", () => {
  it("emits create + terminal transitions", () => {
    const key = `sess-${Math.random()}`;
    const created = diffTaskSnapshots(key, [
      {
        id: "t1",
        status: "queued",
        title: "Job",
        sessionKey: key,
      },
    ]);
    assert.deepEqual(
      created.map((e) => e.name),
      ["task.before_create", "task.after_create"],
    );

    const terminal = diffTaskSnapshots(key, [
      {
        id: "t1",
        status: "succeeded",
        title: "Job",
        sessionKey: key,
      },
    ]);
    assert.deepEqual(terminal.map((e) => e.name), ["task.before_terminal"]);
  });
});

describe("installRuntimeObservers", () => {
  it("names the internal compaction hook registration for OpenClaw", () => {
    let registered:
      | { events: string | string[]; opts?: { name?: string; description?: string } }
      | undefined;
    const api: BridgePluginApi = {
      on: () => {},
      registerHook: (events, _handler, opts) => {
        registered = { events, opts };
      },
    };
    const cfg: BridgeConfig = {
      daemonUrl: "http://127.0.0.1:7878/rpc",
      enabled: false,
      logActivations: false,
      extractOnUserMessage: false,
      runtimeObservers: true,
      observerPollMs: 500,
    };

    installRuntimeObservers(api, cfg, {
      observe: async () => null,
    });

    assert.deepEqual(registered?.events, [
      "session:compact:before",
      "session:compact:after",
    ]);
    assert.equal(registered?.opts?.name, "opencoat-bridge-session-compact");
  });
});
