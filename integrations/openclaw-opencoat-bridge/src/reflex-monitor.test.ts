import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ReflexMonitor } from "./reflex-monitor.js";
import { compileReflexPolicies, DEMO_TOOL_BLOCK_SPEC } from "./reflex-policies.js";
import type { Action, ReflexPolicy, State } from "./reflex-monitor.js";

const state: State = {
  session_id: "s1",
  turn_id: "r1",
  features: {},
};

describe("ReflexMonitor", () => {
  it("allows when no policy applies", () => {
    const monitor = new ReflexMonitor(
      compileReflexPolicies([DEMO_TOOL_BLOCK_SPEC]),
    );
    const action: Action = {
      kind: "tool_call",
      name: "read",
      args: { path: "/tmp/x" },
    };
    const { decision } = monitor.mediate(action, state);
    assert.equal(decision.kind, "allow");
  });

  it("denies rm -rf tool args (demo-tool-block)", () => {
    const monitor = new ReflexMonitor(
      compileReflexPolicies([DEMO_TOOL_BLOCK_SPEC]),
    );
    const action: Action = {
      kind: "tool_call",
      name: "shell.exec",
      args: { command: "rm -rf /tmp/scratch" },
    };
    const { decision } = monitor.mediate(action, state);
    assert.equal(decision.kind, "deny");
    if (decision.kind === "deny") {
      assert.equal(decision.policy_id, "demo-tool-block");
      assert.match(decision.reason, /rm -rf/);
    }
  });

  it("fail-closes when safety_critical policy throws", () => {
    const bad: ReflexPolicy = {
      id: "bad-policy",
      criticality: "safety_critical",
      applies: () => true,
      decide: () => {
        throw new Error("predicate bug");
      },
    };
    const monitor = new ReflexMonitor([bad]);
    const { decision } = monitor.mediate(
      { kind: "tool_call", name: "x", args: {} },
      state,
    );
    assert.equal(decision.kind, "deny");
    if (decision.kind === "deny") {
      assert.match(decision.reason, /fail-closed/i);
    }
  });

  it("deny beats allow from multiple policies", () => {
    const allowAll: ReflexPolicy = {
      id: "allow-a",
      criticality: "advisory",
      applies: () => true,
      decide: () => ({ kind: "allow" }),
    };
    const monitor = new ReflexMonitor([
      allowAll,
      ...compileReflexPolicies([DEMO_TOOL_BLOCK_SPEC]),
    ]);
    const { decision } = monitor.mediate(
      { kind: "tool_call", name: "shell", args: { cmd: "rm -rf /" } },
      state,
    );
    assert.equal(decision.kind, "deny");
  });

  it("does not latch policy_id when advisory policy throws", () => {
    const flaky: ReflexPolicy = {
      id: "flaky-advisory",
      criticality: "advisory",
      applies: () => true,
      decide: () => {
        throw new Error("predicate bug");
      },
    };
    const monitor = new ReflexMonitor([flaky]);
    const { decision, record } = monitor.mediate(
      { kind: "tool_call", name: "read", args: {} },
      state,
    );
    assert.equal(decision.kind, "allow");
    assert.equal(record.policy_id, undefined);
  });
});
