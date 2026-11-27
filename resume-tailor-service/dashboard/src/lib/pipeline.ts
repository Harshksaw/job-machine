// Pure helpers for the Pipeline tab and the schedule settings. No React, so they run
// under node --test.
import type { PipelineAttempt, PipelineConfig, PipelineRunDetail, PipelineRunSummary } from "../types";

/** Task pipelines the worker may run on a timer (app/pipeline/config.py SCHEDULABLE_TASKS). */
export const SCHEDULABLE_TASKS = ["mail_sync", "liveness_sweep", "remote_boards", "ats_watchlist"] as const;
export type SchedulableTask = (typeof SCHEDULABLE_TASKS)[number];

export const TASK_LABELS: Record<SchedulableTask, string> = {
  mail_sync: "Mail sync",
  liveness_sweep: "Liveness sweep",
  remote_boards: "Remote boards",
  ats_watchlist: "ATS watchlist",
};

export const MIN_SCHEDULE_MINUTES = 5;
export const MAX_SCHEDULE_MINUTES = 7 * 24 * 60;

const ACTIVE = new Set(["queued", "running"]);

export function isActive(status: string): boolean {
  return ACTIVE.has(status);
}

/** Minutes between runs, or null when the task is not scheduled or is paused. */
export function scheduleMinutes(config: PipelineConfig, task: string): number | null {
  const schedule = config.schedules?.[task];
  return schedule && schedule.enabled ? schedule.every_minutes : null;
}

/** Sets a task's interval; null removes the schedule (off). Values are clamped to
 * what the API accepts. */
export function setSchedule(config: PipelineConfig, task: string, minutes: number | null): PipelineConfig {
  const schedules = { ...(config.schedules ?? {}) };
  if (minutes === null || !Number.isFinite(minutes)) {
    delete schedules[task];
  } else {
    const every = Math.min(MAX_SCHEDULE_MINUTES, Math.max(MIN_SCHEDULE_MINUTES, Math.round(minutes)));
    schedules[task] = { every_minutes: every, enabled: true };
  }
  return { ...config, schedules };
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  if (value < 1000) return `${value} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  return `${(value / 60_000).toFixed(1)} min`;
}

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `$${value.toFixed(value < 1 ? 4 : 2)}`;
}

export interface RunFilter {
  status: string;
  pipeline: string;
  query: string;
}

export function filterRuns(runs: PipelineRunSummary[], filter: RunFilter): PipelineRunSummary[] {
  const query = filter.query.trim().toLowerCase();
  return runs.filter(
    (run) =>
      (!filter.status || (filter.status === "active" ? isActive(run.status) : run.status === filter.status)) &&
      (!filter.pipeline || run.pipeline === filter.pipeline) &&
      (!query || run.job_id.toLowerCase().includes(query) || run.id.toLowerCase().includes(query))
  );
}

export interface TimelineRow {
  step: string;
  status: string;
  error: string;
  started_at: string;
  finished_at: string;
  attempts: PipelineAttempt[];
}

/** One row per step in run order, each with its attempts oldest first. */
export function stepTimeline(run: PipelineRunDetail): TimelineRow[] {
  const byStep = new Map<string, PipelineAttempt[]>();
  for (const attempt of [...run.attempts].sort((a, b) => a.started_at.localeCompare(b.started_at))) {
    const list = byStep.get(attempt.step) ?? [];
    list.push(attempt);
    byStep.set(attempt.step, list);
  }
  return run.order.map((step) => {
    const state = run.steps[step];
    return {
      step,
      status: state?.status ?? "pending",
      error: state?.error ?? "",
      started_at: state?.started_at ?? "",
      finished_at: state?.finished_at ?? "",
      attempts: byStep.get(step) ?? [],
    };
  });
}

/** Whether a finished run has something to retry without naming a step. */
export function canResume(run: PipelineRunSummary): boolean {
  return !isActive(run.status) && Object.values(run.steps).some((status) => status === "failed");
}

/** A short line for the Research button once a packet run is queued, or skipped. */
export function researchQueuedMessage(result: { queued: { id: string }[]; skipped: string[] }): string {
  if (result.queued.length) {
    return `Queued pipeline run ${result.queued[0].id.slice(0, 8)}. Follow it in the Pipeline tab.`;
  }
  if (result.skipped.length) return "A pipeline run for this dossier is already queued or running. See the Pipeline tab.";
  return "Nothing was queued.";
}
