import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  buildToolBlockedRt,
  buildToolOutcomeRt,
  buildTurnCompleteRt,
} from "./r-t-emit.js";

describe("r_t record builders", () => {
  const ctx = { runId: "run-1", sessionKey: "sk-1" };

  it("builds tool_blocked with reflex metadata", () => {
    const row = buildToolBlockedRt(
      "before_tool_call",
      "before_tool_call",
      ctx,
      "shell.exec",
      {
        turn_id: "run-1",
        action_kind: "tool_call",
        action_name: "shell.exec",
        decision: "deny",
        policy_id: "demo-tool-block",
      },
      "blocked",
    );
    assert.equal(row.event, "r_t");
    assert.equal(row.r, 0);
    assert.equal(row.signal.kind, "tool_blocked");
    assert.equal(row.signal.reflex?.policy_id, "demo-tool-block");
  });

  it("builds tool_outcome success", () => {
    const row = buildToolOutcomeRt(
      "after_tool_call",
      "after_tool_call",
      ctx,
      { toolName: "read", durationMs: 12 },
    );
    assert.equal(row.r, 1);
    assert.equal(row.signal.kind, "tool_outcome");
  });

  it("builds tool_outcome with reflex policy_id for plasticity", () => {
    const row = buildToolOutcomeRt(
      "after_tool_call",
      "after_tool_call",
      ctx,
      { toolName: "read", durationMs: 12 },
      {
        turn_id: "run-1",
        action_kind: "tool_call",
        action_name: "read",
        decision: "rewrite",
        policy_id: "demo-tool-block",
        criticality: "safety_critical",
      },
    );
    assert.equal(row.r, 1);
    assert.equal(row.signal.reflex?.policy_id, "demo-tool-block");
    assert.equal(row.signal.reflex?.decision, "rewrite");
  });

  it("builds turn_complete", () => {
    const row = buildTurnCompleteRt(
      "agent_end",
      "after_response",
      ctx,
      {},
    );
    assert.equal(row.signal.kind, "turn_complete");
    assert.equal(row.r, 1);
  });
});
