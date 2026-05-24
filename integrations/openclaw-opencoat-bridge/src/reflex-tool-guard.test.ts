import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ReflexMonitor } from "./reflex-monitor.js";
import { compileReflexPolicies, DEMO_TOOL_BLOCK_SPEC } from "./reflex-policies.js";
import {
  buildReflexState,
  buildToolCallAction,
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
