import assert from "node:assert/strict";
import test from "node:test";

import { flowSteps, presetRange, visibleRows } from "../src/lib/flow.ts";
import type { FunnelNode, PipelineFunnel } from "../src/types.ts";

function node(key: string, count: number, children: FunnelNode[] = [], kind = "stage"): FunnelNode {
  return { key, label: key, kind, count, children } as FunnelNode;
}

const tree: FunnelNode[] = [
  node("linkedin", 3, [node("A", 3, [node("ready", 2, [node("j1", 1, [], "job"), node("j2", 1, [], "job")])], "tier")], "source"),
  node("remotive", 1, [], "source"),
];

test("only the top level shows until a row is expanded", () => {
  const rows = visibleRows(tree, new Set());
  assert.deepEqual(rows.map((row) => [row.id, row.depth, row.hasChildren]), [
    ["linkedin", 0, true],
    ["remotive", 0, false],
  ]);
});

test("expanding opens one level at a time and ids are paths", () => {
  const rows = visibleRows(tree, new Set(["linkedin", "linkedin/A"]));
  assert.deepEqual(rows.map((row) => row.id), ["linkedin", "linkedin/A", "linkedin/A/ready", "remotive"]);
  assert.equal(rows[2].depth, 2);
  assert.equal(rows[1].expanded, true);
  assert.equal(rows[2].expanded, false);
  const deeper = visibleRows(tree, new Set(["linkedin", "linkedin/A", "linkedin/A/ready"]));
  assert.deepEqual(deeper.slice(3, 5).map((row) => row.id), ["linkedin/A/ready/j1", "linkedin/A/ready/j2"]);
});

test("a collapsed parent hides its expanded children", () => {
  const rows = visibleRows(tree, new Set(["linkedin/A"]));
  assert.deepEqual(rows.map((row) => row.id), ["linkedin", "remotive"]);
});

const funnel: PipelineFunnel = {
  since: "",
  until: "",
  generated_at: "",
  total: 20,
  stages: {
    research_new: 4, dismissed: 2, promoted: 1, discovered: 3, ineligible: 2, retained: 3, eligible: 1,
    ready: 1, packet_ready: 1, applying: 0, applied: 1, outreach: 0, interview: 1, offer: 0, rejected: 0,
    closed: 0, skipped: 0, archived: 0,
  },
  stage_labels: {},
  tiers: { A: 10, A2: 6, E: 3, unknown: 1 },
  harvest: { run_at: "2026-11-26T08:00:00+00:00", fetched: 500, kept: 40, dropped: 460 },
  events: {},
  tree: [],
};

test("the flow boxes follow the pipeline order and carry live counts", () => {
  const steps = flowSteps(funnel);
  assert.deepEqual(steps.map((step) => step.key), [
    "source", "region", "eligibility", "fit", "packet", "apply", "outcome",
  ]);
  const byKey = Object.fromEntries(steps.map((step) => [step.key, step]));
  assert.equal(byKey.source.count, 20);
  assert.deepEqual(byKey.source.parts.find((p) => p.label === "Fetched by the last harvest")?.count, 500);
  assert.equal(byKey.region.parts.find((p) => p.label === "Dropped by the filter")?.count, 460);
  assert.equal(byKey.eligibility.parts.find((p) => p.label === "Ineligible")?.count, 2);
  assert.equal(byKey.eligibility.parts.find((p) => p.label === "Waiting")?.count, 8);
  assert.equal(byKey.fit.parts.find((p) => p.label === "Retained, fit too low")?.count, 3);
  assert.equal(byKey.packet.count, 2);
  assert.equal(byKey.apply.count, 1);
  assert.equal(byKey.outcome.count, 1);
  for (const step of steps) {
    assert.ok(!/[—–]/.test(step.title + step.explain), `no long dashes in ${step.key}`);
  }
});

test("without a harvest file the source box has no fetched part", () => {
  const steps = flowSteps({ ...funnel, harvest: null });
  assert.equal(steps[0].parts.some((p) => p.label === "Fetched by the last harvest"), false);
  assert.equal(steps[1].parts.some((p) => p.label === "Dropped by the filter"), false);
});

test("date presets give a since date and no until", () => {
  const today = new Date("2026-11-27T15:00:00Z");
  assert.deepEqual(presetRange("all", today), { since: "", until: "" });
  assert.deepEqual(presetRange("7d", today), { since: "2026-11-20", until: "" });
  assert.deepEqual(presetRange("30d", today), { since: "2026-10-28", until: "" });
});
