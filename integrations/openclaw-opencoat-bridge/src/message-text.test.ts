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

  it("clears later text parts when replacing array content", () => {
    const out = applyAgentMessageContent(
      {
        role: "toolResult",
        content: [
          { type: "image", url: "file.png" },
          { type: "text", text: "first secret" },
          { type: "text", text: "second secret" },
        ],
      },
      "[redacted]",
    ) as { content: Array<{ text?: string; type?: string; url?: string }> };
    assert.deepEqual(out.content, [
      { type: "image", url: "file.png" },
      { type: "text", text: "[redacted]" },
      { type: "text", text: "" },
    ]);
  });

  it("does not leave later string parts unchanged", () => {
    const out = applyAgentMessageContent(
      { role: "toolResult", content: ["first secret", "second secret"] },
      "[redacted]",
    ) as { content: string[] };
    assert.deepEqual(out.content, ["[redacted]", ""]);
  });

  it("prepends text when array content has no text parts", () => {
    const out = applyAgentMessageContent(
      { role: "toolResult", content: [{ type: "image", url: "file.png" }] },
      "[redacted]",
    ) as { content: Array<{ text?: string; type?: string; url?: string }> };
    assert.deepEqual(out.content, [
      { type: "text", text: "[redacted]" },
      { type: "image", url: "file.png" },
    ]);
  });
});
