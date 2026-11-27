import assert from "node:assert/strict";
import test from "node:test";

import {
  clampInt,
  disabledPicks,
  eligibleAdapters,
  formatApiDetail,
  isDirty,
  moveItem,
  percentToShare,
  setStepPrefs,
  shareToPercent,
  stepPrefs,
  toggleCapability,
  updateAdapter,
} from "../src/lib/agents.ts";
import type { AdapterSpec, PipelineConfig } from "../src/types.ts";

function adapter(patch: Partial<AdapterSpec>): AdapterSpec {
  return {
    name: "",
    type: "cli",
    command: ["tool", "{prompt}"],
    output: "file",
    isolation: "",
    provider: "",
    model: "",
    key_env: "",
    env: {},
    capabilities: ["reason"],
    cost_tier: 2,
    max_parallel: 1,
    enabled: true,
    timeouts: {},
    family: "",
    ...patch,
  };
}

function config(): PipelineConfig {
  return {
    workers: 4,
    adapters: {
      codex: adapter({ name: "codex", capabilities: ["reason", "web"], cost_tier: 3 }),
      gemini_lite: adapter({ name: "gemini_lite", type: "api", model: "m", capabilities: ["cheap"], cost_tier: 1 }),
      claude_haiku: adapter({ name: "claude_haiku", capabilities: ["cheap", "reason"], cost_tier: 2 }),
    },
    capability_caps: {},
    steps: {},
    version: 3,
    updated_at: "2026-11-26T00:00:00Z",
  };
}

test("formatApiDetail reads strings, string lists and pydantic errors", () => {
  assert.deepEqual(formatApiDetail("no config version 9"), ["no config version 9"]);
  assert.deepEqual(formatApiDetail(["step fit_score prefers gemini_lite, which lacks capability reason"]), [
    "step fit_score prefers gemini_lite, which lacks capability reason",
  ]);
  assert.deepEqual(
    formatApiDetail([
      {
        type: "value_error",
        loc: ["body", "adapters", "codex"],
        msg: "Value error, a cli adapter needs a command with a {prompt} placeholder",
      },
    ]),
    ["adapters.codex: a cli adapter needs a command with a {prompt} placeholder"]
  );
  assert.deepEqual(formatApiDetail({ odd: true }), []);
});

test("isDirty ignores the version stamp", () => {
  const saved = config();
  assert.equal(isDirty(saved, { ...saved, version: 9, updated_at: "later" }), false);
  assert.equal(isDirty(saved, updateAdapter(saved, "codex", { enabled: false })), true);
  assert.equal(isDirty(null, saved), false);
});

test("updateAdapter patches one adapter and leaves the original alone", () => {
  const before = config();
  const after = updateAdapter(before, "gemini_lite", { model: "gemini-next" });
  assert.equal(after.adapters.gemini_lite.model, "gemini-next");
  assert.equal(before.adapters.gemini_lite.model, "m");
  assert.equal(updateAdapter(before, "ghost", { enabled: false }), before);
});

test("toggleCapability keeps the canonical order", () => {
  assert.deepEqual(toggleCapability(["web"], "cheap"), ["cheap", "web"]);
  assert.deepEqual(toggleCapability(["cheap", "web"], "cheap"), ["web"]);
});

test("eligibleAdapters lists only adapters with the capability, cheapest first", () => {
  assert.deepEqual(eligibleAdapters(config(), "reason"), ["claude_haiku", "codex"]);
  assert.deepEqual(eligibleAdapters(config(), "cheap"), ["gemini_lite", "claude_haiku"]);
  assert.deepEqual(eligibleAdapters(config(), "browser_read"), []);
});

test("setStepPrefs drops a step with nothing set", () => {
  let next = setStepPrefs(config(), "fit_score", { prefer: ["codex"], canary: null });
  assert.deepEqual(stepPrefs(next, "fit_score").prefer, ["codex"]);
  next = setStepPrefs(next, "fit_score", { prefer: [], canary: null });
  assert.equal("fit_score" in next.steps, false);
  next = setStepPrefs(next, "kit", { prefer: [], canary: { adapter: "codex", share: 0.2 } });
  assert.deepEqual(next.steps.kit.canary, { adapter: "codex", share: 0.2 });
  assert.deepEqual(stepPrefs(next, "review"), { prefer: [], canary: null });
});

test("moveItem swaps neighbours and ignores moves off the ends", () => {
  assert.deepEqual(moveItem(["a", "b", "c"], 1, -1), ["b", "a", "c"]);
  assert.deepEqual(moveItem(["a", "b", "c"], 2, 1), ["a", "b", "c"]);
  assert.deepEqual(moveItem(["a", "b", "c"], 0, -1), ["a", "b", "c"]);
});

test("percent and share convert both ways and clamp", () => {
  assert.equal(percentToShare("20"), 0.2);
  assert.equal(percentToShare("150"), 1);
  assert.equal(percentToShare("-5"), 0);
  assert.equal(percentToShare("abc"), 0);
  assert.equal(shareToPercent(0.125), 12.5);
});

test("clampInt parses whole numbers inside a range", () => {
  assert.equal(clampInt("5", 1, 32, 2), 5);
  assert.equal(clampInt("99", 1, 32, 2), 32);
  assert.equal(clampInt("0", 1, 32, 2), 1);
  assert.equal(clampInt("", 1, 32, 2), 2);
});

test("eligibleAdapters leaves out disabled adapters, which the router never uses", () => {
  const off = updateAdapter(config(), "codex", { enabled: false });
  assert.deepEqual(eligibleAdapters(off, "reason"), ["claude_haiku"]);
});

test("disabledPicks names preferred or canary adapters that are switched off", () => {
  let next = setStepPrefs(config(), "fit_score", {
    prefer: ["codex", "claude_haiku"],
    canary: { adapter: "codex", share: 0.2 },
  });
  assert.deepEqual(disabledPicks(next, "fit_score"), []);
  next = updateAdapter(next, "codex", { enabled: false });
  assert.deepEqual(disabledPicks(next, "fit_score"), ["codex"]);
  assert.deepEqual(disabledPicks(next, "kit"), []);
});
