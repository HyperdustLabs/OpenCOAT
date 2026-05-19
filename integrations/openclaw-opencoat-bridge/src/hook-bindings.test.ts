import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { HOOK_BINDINGS, SKIPPED_HOOKS } from "./hook-bindings.js";

describe("hook-bindings", () => {
  it("registers all async-safe plugin hooks (29 total minus 3 skipped)", () => {
    assert.equal(HOOK_BINDINGS.length, 26);
    assert.equal(SKIPPED_HOOKS.length, 3);
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
      "subagent_spawning",
      "before_compaction",
    ]) {
      assert.ok(hooks.has(required), `missing ${required}`);
    }
  });
});
