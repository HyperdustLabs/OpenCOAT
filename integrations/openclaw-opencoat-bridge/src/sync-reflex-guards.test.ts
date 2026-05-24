import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { ReflexMonitor } from "./reflex-monitor.js";
import { compileReflexPolicies } from "./reflex-policies.js";
import type { ReflexPolicySpec } from "./reflex-policy-spec.js";
import {
  buildMemoryWriteAction,
  buildReflexState,
  reflexMemoryWriteDecision,
  reflexMessageGuardDecision,
  reflexToolResultPersistDecision,
} from "./reflex-tool-guard.js";
import { buildPayloadAction } from "./reflex-policies.js";
import { handleBeforeMessageWriteSync } from "./sync-reflex-guards.js";
import { buildReflexRuntime } from "./reflex-policy-sync.js";

const MEMORY_BLOCK: ReflexPolicySpec = {
  id: "mem-block-secret",
  criticality: "safety_critical",
  action_kind: "memory_write",
  predicate: { kind: "text_contains", needles: ["TOP_SECRET"] },
  deny_reason: "Secret content blocked from session JSONL.",
};

const MESSAGE_REWRITE: ReflexPolicySpec = {
  id: "msg-repair",
  criticality: "advisory",
  action_kind: "message_out",
  effect: "rewrite",
  predicate: { kind: "text_contains", needles: ["LEAK_ME"] },
  deny_reason: "Outbound leak repaired.",
  rewrite_content: "[OpenCOAT repaired outbound]",
};

describe("reflexMessageGuardDecision", () => {
  const monitor = new ReflexMonitor(compileReflexPolicies([MESSAGE_REWRITE]));

  it("rewrites outbound content (verify→repair)", () => {
    const action = buildPayloadAction("message_out", {
      content: "please LEAK_ME now",
    });
    const out = reflexMessageGuardDecision(
      monitor,
      action,
      buildReflexState({}),
    );
    assert.equal(out.cancel, undefined);
    assert.equal(out.content, "[OpenCOAT repaired outbound]");
  });
});

describe("reflexMemoryWriteDecision", () => {
  const monitor = new ReflexMonitor(compileReflexPolicies([MEMORY_BLOCK]));

  it("blocks session write when needle matches", () => {
    const message = { role: "user", content: "TOP_SECRET payload" };
    const action = buildMemoryWriteAction(message);
    const out = reflexMemoryWriteDecision(
      monitor,
      action,
      buildReflexState({}),
      message,
    );
    assert.equal(out.block, true);
  });
});

describe("reflexToolResultPersistDecision", () => {
  const spec: ReflexPolicySpec = {
    id: "tr-redact",
    criticality: "safety_critical",
    action_kind: "tool_result_persist",
    effect: "rewrite",
    predicate: { kind: "text_contains", needles: ["api_key="] },
    deny_reason: "Redact secrets in persisted tool results.",
    rewrite_content: "[redacted tool result]",
  };
  const monitor = new ReflexMonitor(compileReflexPolicies([spec]));

  it("rewrites persisted tool result text", () => {
    const message = {
      role: "toolResult",
      content: [{ type: "text", text: "api_key=abc123" }],
    };
    const action = buildPayloadAction("tool_result_persist", {
      text: "api_key=abc123",
      content: "api_key=abc123",
    });
    const out = reflexToolResultPersistDecision(
      monitor,
      action,
      buildReflexState({}),
      message,
    );
    const text = (out.message as { content: Array<{ text: string }> }).content[0]
      ?.text;
    assert.equal(text, "[redacted tool result]");
  });
});

describe("handleBeforeMessageWriteSync", () => {
  it("returns block synchronously (no Promise)", () => {
    const cfg = {
      daemonUrl: "http://127.0.0.1:7878/rpc",
      enabled: true,
      logActivations: false,
      extractOnUserMessage: false,
      runtimeObservers: false,
      observerPollMs: 500,
      inProcReflexToolGuard: true,
      inProcReflexGuards: true,
      reflexSyncFromDaemon: false,
      reflexAuditToDaemon: false,
      reflexPolicies: [MEMORY_BLOCK],
      reflexIncludeDemoPolicy: false,
      emitRtJsonl: false,
    };
    const runtime = buildReflexRuntime(cfg, null);
    const out = handleBeforeMessageWriteSync(
      cfg,
      runtime,
      { message: { role: "user", content: "TOP_SECRET" } },
      { sessionKey: "sk" },
    );
    assert.equal(out?.block, true);
    assert.notEqual(typeof (out as Promise<unknown>)?.then, "function");
  });
});
