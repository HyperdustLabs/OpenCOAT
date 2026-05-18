import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { normalizeMessage, normalizeMessages, promptPayload } from "./messages.js";

describe("normalizeMessage", () => {
  it("maps OpenAI-style user content", () => {
    const m = normalizeMessage({ role: "user", content: "hello shell" });
    assert.ok(m);
    assert.equal(m.role, "user");
    assert.equal(m.content, "hello shell");
  });

  it("extracts text parts from multimodal content", () => {
    const m = normalizeMessage({
      role: "user",
      content: [{ type: "text", text: "rm -rf" }],
    });
    assert.ok(m);
    assert.equal(m.content, "rm -rf");
  });

  it("preserves sections for prompt_section joinpoints", () => {
    const m = normalizeMessage({
      role: "system",
      content: "rules",
      sections: [{ path: "runtime_prompt.rules", raw_text: "no rm" }],
    });
    assert.ok(m?.sections?.length);
    assert.equal(m.sections![0].path, "runtime_prompt.rules");
  });
});

describe("promptPayload", () => {
  it("includes messages array when history is present", () => {
    const p = promptPayload({
      parts: ["system preamble"],
      messages: [
        { role: "user", content: "use shell" },
        { role: "assistant", content: "ok" },
      ],
    });
    assert.ok(Array.isArray(p.messages));
    assert.equal((p.messages as unknown[]).length, 2);
    assert.match(String(p.text), /use shell/);
    assert.match(String(p.text), /system preamble/);
  });

  it("keeps section-only messages for prompt_section discovery", () => {
    const p = promptPayload({
      messages: [
        {
          role: "system",
          sections: [
            {
              path: "runtime_prompt.rules",
              raw_text: "Never run rm -rf in shell.",
            },
          ],
        },
      ],
    });
    const msgs = p.messages as { sections?: unknown[] }[];
    assert.equal(msgs.length, 1);
    assert.equal(msgs[0].sections?.length, 1);
    assert.match(String(p.text), /rm -rf/);
  });

  it("normalizeMessages caps at 64", () => {
    const many = Array.from({ length: 80 }, (_, i) => ({
      role: "user",
      content: `m${i}`,
    }));
    assert.equal(normalizeMessages(many).length, 64);
  });
});
