import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { queueBeforeEnqueueDecision } from "./injector.js";
import type { ConcernInjection } from "./types.js";

function injection(rows: ConcernInjection["injections"]): ConcernInjection {
  return {
    weave_id: "weave-1",
    agent_session_id: "session-1",
    injections: rows,
  };
}

describe("queueBeforeEnqueueDecision", () => {
  it("blocks queue enqueue from blocking advice", () => {
    const decision = queueBeforeEnqueueDecision(
      injection([
        {
          concern_id: "queue-policy",
          advice_type: "memory_write_guard",
          target: "queue.prompt",
          mode: "block",
          content: "Queue is full for this policy.",
        },
      ]),
    );

    assert.deepEqual(decision, {
      block: true,
      blockReason: "Queue is full for this policy.",
    });
  });

  it("rewrites prompt and summary line from queue targets", () => {
    const decision = queueBeforeEnqueueDecision(
      injection([
        {
          concern_id: "rewrite",
          advice_type: "rewrite_guidance",
          target: "queue.prompt",
          mode: "rewrite",
          content: "Summarized follow-up prompt",
        },
        {
          concern_id: "summary",
          advice_type: "rewrite_guidance",
          target: "queue.summary_line",
          mode: "rewrite",
          content: "Short summary",
        },
      ]),
    );

    assert.deepEqual(decision, {
      prompt: "Summarized follow-up prompt",
      summaryLine: "Short summary",
    });
  });

  it("ignores non-queue append advice", () => {
    const decision = queueBeforeEnqueueDecision(
      injection([
        {
          concern_id: "prompt-note",
          advice_type: "response_requirement",
          target: "runtime_prompt.output_format",
          mode: "insert",
          content: "Answer in JSON.",
        },
      ]),
    );

    assert.deepEqual(decision, {});
  });
});
