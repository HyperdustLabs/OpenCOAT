import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  agentEventJoinpoint,
  agentEventRunningJoinpoint,
  diffQueueDepth,
  diffTaskSnapshots,
} from "./runtime-observers.js";

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
