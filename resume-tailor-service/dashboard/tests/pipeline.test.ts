import assert from "node:assert/strict";
import test from "node:test";

import {
  canResume,
  filterRuns,
  formatCost,
  formatMs,
  researchQueuedMessage,
  scheduleMinutes,
  setSchedule,
  stepTimeline,
} from "../src/lib/pipeline.ts";
import type { PipelineConfig, PipelineRunDetail, PipelineRunSummary } from "../src/types.ts";

const config: PipelineConfig = {
  workers: 4,
  adapters: {},
  capability_caps: {},
  steps: {},
  version: 3,
  updated_at: "",
};

test("schedules default to off, clamp, and can be removed", () => {
  assert.equal(scheduleMinutes(config, "mail_sync"), null);
  const on = setSchedule(config, "mail_sync", 60);
  assert.deepEqual(on.schedules, { mail_sync: { every_minutes: 60, enabled: true } });
  assert.equal(scheduleMinutes(on, "mail_sync"), 60);
  assert.equal(config.schedules, undefined, "the input is not mutated");
  assert.equal(setSchedule(config, "mail_sync", 1).schedules!.mail_sync.every_minutes, 5);
  assert.equal(setSchedule(config, "mail_sync", 1e9).schedules!.mail_sync.every_minutes, 10080);
  assert.deepEqual(setSchedule(on, "mail_sync", null).schedules, {});
  const paused = { ...config, schedules: { mail_sync: { every_minutes: 30, enabled: false } } };
  assert.equal(scheduleMinutes(paused, "mail_sync"), null);
});

function summary(patch: Partial<PipelineRunSummary>): PipelineRunSummary {
  return {
    id: "r1", job_id: "j1", pipeline: "packet", status: "failed", terminal_reason: "",
    created_at: "", updated_at: "", steps: {}, ...patch,
  };
}

test("run filters by status, the active group, pipeline and id", () => {
  const runs = [
    summary({ id: "a", status: "queued" }),
    summary({ id: "b", status: "running", pipeline: "mail_sync", job_id: "task:mail_sync" }),
    summary({ id: "c", status: "failed", job_id: "abc123" }),
  ];
  assert.deepEqual(filterRuns(runs, { status: "active", pipeline: "", query: "" }).map((r) => r.id), ["a", "b"]);
  assert.deepEqual(filterRuns(runs, { status: "failed", pipeline: "", query: "" }).map((r) => r.id), ["c"]);
  assert.deepEqual(filterRuns(runs, { status: "", pipeline: "mail_sync", query: "" }).map((r) => r.id), ["b"]);
  assert.deepEqual(filterRuns(runs, { status: "", pipeline: "", query: "ABC" }).map((r) => r.id), ["c"]);
});

test("timeline lists steps in run order with their attempts", () => {
  const attempt = (step: string, at: string, outcome = "ok") => ({
    id: at, run_id: "r1", job_id: "j1", step, adapter: "x", model: "", prompt_version: "",
    started_at: at, duration_ms: 1, outcome, error: "", tokens_in: null, tokens_out: null, cost: null, output_ref: "",
  });
  const run: PipelineRunDetail = {
    id: "r1", job_id: "j1", pipeline: "packet", status: "failed", order: ["b", "a"],
    steps: {
      a: { status: "pending", output: null, error: "", started_at: "", finished_at: "" },
      b: { status: "failed", output: null, error: "boom", started_at: "t1", finished_at: "t3" },
    },
    terminal_reason: "", lease_owner: "", lease_until: "", created_at: "", updated_at: "",
    attempts: [attempt("b", "2", "invalid_output"), attempt("b", "1", "timeout")],
  };
  const rows = stepTimeline(run);
  assert.deepEqual(rows.map((row) => row.step), ["b", "a"]);
  assert.deepEqual(rows[0].attempts.map((a) => a.outcome), ["timeout", "invalid_output"]);
  assert.equal(rows[0].error, "boom");
  assert.deepEqual(rows[1].attempts, []);
});

test("resume needs a finished run with a failed step", () => {
  assert.equal(canResume(summary({ steps: { a: "failed" } })), true);
  assert.equal(canResume(summary({ status: "running", steps: { a: "failed" } })), false);
  assert.equal(canResume(summary({ status: "packet_ready", steps: { a: "done" } })), false);
});

test("formatting and the research message", () => {
  assert.equal(formatMs(null), "n/a");
  assert.equal(formatMs(250), "250 ms");
  assert.equal(formatMs(1500), "1.5 s");
  assert.equal(formatMs(90_000), "1.5 min");
  assert.equal(formatCost(null), "n/a");
  assert.equal(formatCost(0.0123), "$0.0123");
  assert.match(researchQueuedMessage({ queued: [{ id: "abcdef123456" }], skipped: [] }), /abcdef12/);
  assert.match(researchQueuedMessage({ queued: [], skipped: ["j1"] }), /already queued/);
});
