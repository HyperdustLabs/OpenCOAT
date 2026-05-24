import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ReflexMonitor } from "./reflex-monitor.js";
import { compileReflexPolicies, DEMO_TOOL_BLOCK_SPEC } from "./reflex-policies.js";
import {
  buildReflexState,
  buildToolCallAction,
  failClosedMessageGuard,
  failClosedQueueGuard,
  failClosedSpawnGuard,
  failClosedToolGuard,
  reflexToolGuardDecision,
} from "./reflex-tool-guard.js";

describe("reflexToolGuardDecision", () => {
  const monitor = new ReflexMonitor(
    compileReflexPolicies([DEMO_TOOL_BLOCK_SPEC]),
  );

  it("maps deny to OpenClaw block shape", () => {
    const params = { command: "rm -rf /tmp/x" };
    const action = buildToolCallAction({ toolName: "shell.exec", params });
    const out = reflexToolGuardDecision(
      monitor,
      action,
      buildReflexState({ runId: "run-1", sessionKey: "sk" }),
      params,
    );
    assert.equal(out.block, true);
    assert.ok(out.blockReason);
  });

  it("allows benign tool calls", () => {
    const params = { command: "ls -la" };
    const action = buildToolCallAction({ toolName: "shell.exec", params });
    const out = reflexToolGuardDecision(
      monitor,
      action,
      buildReflexState({}),
      params,
    );
    assert.equal(out.block, false);
  });
});

describe("in-proc fail-closed helpers", () => {
  const err = new Error("monitor blew up");

  it("failClosedToolGuard blocks with reason", () => {
    const out = failClosedToolGuard({ command: "x" }, err);
    assert.equal(out.block, true);
    assert.match(out.blockReason ?? "", /monitor blew up/);
  });

  it("failClosedMessageGuard cancels send", () => {
    const out = failClosedMessageGuard(err);
    assert.equal(out.cancel, true);
    assert.match(out.content, /monitor blew up/);
  });

  it("failClosedSpawnGuard returns error status", () => {
    const out = failClosedSpawnGuard(err);
    assert.equal(out.status, "error");
    assert.match(out.error, /monitor blew up/);
  });

  it("failClosedQueueGuard blocks enqueue", () => {
    const out = failClosedQueueGuard(err);
    assert.equal(out.block, true);
    assert.match(out.blockReason, /monitor blew up/);
  });
});
