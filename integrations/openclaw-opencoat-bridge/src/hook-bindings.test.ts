import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { HOOK_BINDINGS, SKIPPED_HOOKS, SYNC_HOOK_BINDINGS } from "./hook-bindings.js";

describe("hook-bindings", () => {
  it("registers async-safe plugin hooks plus native queue hooks", () => {
    assert.equal(HOOK_BINDINGS.length, 29);
    assert.equal(SYNC_HOOK_BINDINGS.length, 2);
    assert.equal(SKIPPED_HOOKS.length, 1);
  });

  it("has unique hook names", () => {
    const names = HOOK_BINDINGS.map((b) => b.hook);
    assert.equal(names.length, new Set(names).size);
  });

  it("covers core weave hooks", () => {
    const hooks = new Set(HOOK_BINDINGS.map((b) => b.hook));
    for (const required of [
      "before_prompt_build",
      "before_tool_call",
      "after_tool_call",
      "queue_before_enqueue",
      "queue_after_enqueue",
      "subagent_spawning",
      "before_compaction",
    ]) {
      assert.ok(hooks.has(required), `missing ${required}`);
    }
  });
});
