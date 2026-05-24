import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  applyAgentMessageContent,
  extractAgentMessageText,
} from "./message-text.js";

describe("extractAgentMessageText", () => {
  it("reads string content", () => {
    assert.equal(
      extractAgentMessageText({ role: "user", content: "hello" }),
      "hello",
    );
  });

  it("joins text parts", () => {
    assert.equal(
      extractAgentMessageText({
        role: "toolResult",
        content: [{ type: "text", text: "part-a" }, { type: "text", text: "part-b" }],
      }),
      "part-apart-b",
    );
  });
});

describe("applyAgentMessageContent", () => {
  it("replaces string content", () => {
    const out = applyAgentMessageContent(
      { role: "assistant", content: "old" },
      "new",
    ) as { content: string };
    assert.equal(out.content, "new");
  });

  it("replaces first text part in array content", () => {
    const out = applyAgentMessageContent(
      { role: "toolResult", content: [{ type: "text", text: "secret" }] },
      "[redacted]",
    ) as { content: Array<{ text: string }> };
    assert.equal(out.content[0]?.text, "[redacted]");
  });
});
