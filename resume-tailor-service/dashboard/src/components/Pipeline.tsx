import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Ban, Play, RefreshCw, RotateCcw, Workflow } from "lucide-react";
import {
  ApiError,
  PipelineError,
  cancelPipelineRun,
  enqueuePipelineRuns,
  getPipelineRun,
  getPipelineStats,
  getPipelineWorker,
  listPipelineAdapters,
  listPipelineRuns,
  retryPipelineRun,
} from "../api";
import {
  SCHEDULABLE_TASKS,
  TASK_LABELS,
  canResume,
  filterRuns,
  formatCost,
  formatMs,
  isActive,
  stepTimeline,
  type RunFilter,
} from "../lib/pipeline";
import type {
  AdapterStatus,
  PipelineRunDetail,
  PipelineRunSummary,
  PipelineStats,
  PipelineWorkerStatus,
} from "../types";

const HEADING = "flex items-center gap-2 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100";
const STATUSES = [
  "active",
  "queued",
  "running",
  "packet_ready",
  "retained_for_review",
  "ineligible",
  "closed_posting",
  "completed",
  "failed",
  "cancelled",
];

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof PipelineError) return error.lines.join("; ");
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return fallback;
}

function tone(status: string): string {
  if (status === "failed" || status === "cancelled") return "text-rose-300";
  if (status === "running" || status === "queued") return "text-amber-300";
  if (status === "done" || status === "packet_ready" || status === "completed") return "text-teal-300";
  return "text-zinc-400";
}

function RunDetail({
  run,
  busy,
  onRetry,
  onCancel,
}: {
  run: PipelineRunDetail;
  busy: boolean;
  onRetry: (step?: string) => void;
  onCancel: () => void;
}) {
  const rows = stepTimeline(run);
  const active = isActive(run.status);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-zinc-100">{run.pipeline}</span>
        <span className="text-zinc-500">{run.job_id}</span>
        <span className={tone(run.status)}>{run.status}</span>
        {run.terminal_reason && <span className="text-xs text-zinc-400">{run.terminal_reason}</span>}
        <span className="ml-auto flex gap-2">
          {active ? (
            <button type="button" className="jm-btn-ghost h-7 px-2 text-xs" onClick={onCancel} disabled={busy}>
              <Ban className="h-3.5 w-3.5" aria-hidden /> Cancel
            </button>
          ) : (
            rows.some((row) => row.status === "failed") && (
              <button type="button" className="jm-btn-ghost h-7 px-2 text-xs" onClick={() => onRetry()} disabled={busy}>
                <RotateCcw className="h-3.5 w-3.5" aria-hidden /> Retry from first failure
              </button>
            )
          )}
        </span>
      </div>
      {run.lease_owner && (
        <p className="text-xs text-zinc-500">
          Leased by {run.lease_owner} until {when(run.lease_until)}
        </p>
      )}
      <ol className="divide-y divide-zinc-800">
        {rows.map((row) => (
          <li key={row.step} className="py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-36 shrink-0 font-medium text-zinc-100">{row.step}</span>
              <span className={`w-20 text-xs ${tone(row.status)}`}>{row.status}</span>
              <span className="text-xs text-zinc-500">
                {row.started_at && when(row.started_at)}
                {row.finished_at && ` to ${when(row.finished_at)}`}
              </span>
              {!active && row.status !== "pending" && (
                <button
                  type="button"
                  className="jm-btn-ghost ml-auto h-6 px-2 text-xs"
                  onClick={() => onRetry(row.step)}
                  disabled={busy}
                  title="Rerun this step and every step after it"
                >
                  Rerun from here
                </button>
              )}
            </div>
            {row.error && <p className="mt-1 text-xs text-rose-300">{row.error}</p>}
            {row.attempts.length > 0 && (
              <ul className="mt-1 space-y-0.5 pl-4 text-xs text-zinc-400">
                {row.attempts.map((attempt, index) => (
                  <li key={attempt.id}>
                    <span className="text-zinc-500">{index + 1}.</span> {attempt.adapter}
                    {attempt.model && <span className="text-zinc-500"> ({attempt.model})</span>}{" "}
                    <span className={attempt.outcome === "ok" ? "text-teal-300" : "text-rose-300"}>{attempt.outcome}</span>{" "}
                    {formatMs(attempt.duration_ms)}
                    {attempt.cost !== null && ` · ${formatCost(attempt.cost)}`}
                    {attempt.error && <span className="block truncate text-zinc-500">{attempt.error}</span>}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default function Pipeline() {
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [selected, setSelected] = useState<PipelineRunDetail | null>(null);
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [adapters, setAdapters] = useState<AdapterStatus[]>([]);
  const [workerStatus, setWorkerStatus] = useState<PipelineWorkerStatus | null>(null);
  const [filter, setFilter] = useState<RunFilter>({ status: "", pipeline: "", query: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [runRows, statRows, adapterRows, status] = await Promise.all([
        listPipelineRuns({ limit: 200 }),
        getPipelineStats(),
        listPipelineAdapters(),
        getPipelineWorker(),
      ]);
      setRuns(runRows);
      setStats(statRows);
      setAdapters(adapterRows);
      setWorkerStatus(status);
      setError("");
    } catch (err) {
      setError(errorText(err, "Failed to load the pipeline."));
    }
  }, []);

  const open = useCallback(async (id: string) => {
    try {
      setSelected(await getPipelineRun(id));
    } catch (err) {
      setError(errorText(err, "Failed to load the run."));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  // Keep the open run fresh while it is still going.
  useEffect(() => {
    if (!selected || !isActive(selected.status)) return;
    const timer = window.setInterval(() => void open(selected.id), 5_000);
    return () => window.clearInterval(timer);
  }, [selected, open]);

  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(done);
      await load();
      if (selected) await open(selected.id);
    } catch (err) {
      setError(errorText(err, "Request failed."));
    } finally {
      setBusy(false);
    }
  };

  const shown = useMemo(() => filterRuns(runs, filter), [runs, filter]);
  const pipelines = useMemo(() => Array.from(new Set(runs.map((run) => run.pipeline))).sort(), [runs]);

  return (
    <div className="h-full space-y-4 overflow-y-auto pb-6">
      <section className="jm-panel p-4" aria-label="Worker">
        <h2 className={HEADING}>
          <Workflow className="h-4 w-4 text-teal-300" aria-hidden /> Pipeline
          <button type="button" className="jm-btn-ghost ml-auto h-7 px-2 text-xs" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
          </button>
        </h2>
        <p className="mt-2 text-sm text-zinc-300">
          {workerStatus === null
            ? "Checking the worker..."
            : workerStatus.running
              ? `The worker pool is running with ${workerStatus.workers} ${workerStatus.workers === 1 ? "worker" : "workers"}.`
              : "The worker pool is off (PIPELINE_WORKERS is 0 or unset), so queued runs wait until it is turned on or scripts/run_task.py drains them."}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {SCHEDULABLE_TASKS.map((task) => (
            <button
              key={task}
              type="button"
              className="jm-btn-ghost h-8 px-2 text-xs"
              disabled={busy}
              onClick={() => void act(() => enqueuePipelineRuns(task), `${TASK_LABELS[task]} queued.`)}
            >
              <Play className="h-3.5 w-3.5" aria-hidden /> Run {TASK_LABELS[task].toLowerCase()}
            </button>
          ))}
        </div>
        {notice && <p className="mt-2 text-xs text-teal-300">{notice}</p>}
        {error && (
          <p role="alert" className="mt-2 text-xs text-rose-300">
            {error}
          </p>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="jm-panel p-4" aria-label="Runs">
          <h3 className={HEADING}>Runs</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            <select
              className="jm-input h-8 w-auto py-0 text-xs"
              value={filter.status}
              onChange={(event) => setFilter({ ...filter, status: event.target.value })}
              aria-label="Filter by status"
            >
              <option value="">Any status</option>
              {STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status === "active" ? "queued or running" : status}
                </option>
              ))}
            </select>
            <select
              className="jm-input h-8 w-auto py-0 text-xs"
              value={filter.pipeline}
              onChange={(event) => setFilter({ ...filter, pipeline: event.target.value })}
              aria-label="Filter by pipeline"
            >
              <option value="">Any pipeline</option>
              {pipelines.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <input
              className="jm-input h-8 w-40 py-0 text-xs"
              placeholder="Dossier or run id"
              value={filter.query}
              onChange={(event) => setFilter({ ...filter, query: event.target.value })}
              aria-label="Filter by dossier or run id"
            />
          </div>
          <ul className="mt-2 max-h-[28rem] divide-y divide-zinc-800 overflow-y-auto">
            {shown.length === 0 && <li className="py-3 text-sm text-zinc-500">No runs match.</li>}
            {shown.map((run) => (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => void open(run.id)}
                  className={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-1 py-2 text-left text-sm hover:bg-zinc-900 ${
                    selected?.id === run.id ? "bg-zinc-900" : ""
                  }`}
                >
                  <span className="w-24 shrink-0 font-medium text-zinc-100">{run.pipeline}</span>
                  <span className={`w-36 shrink-0 text-xs ${tone(run.status)}`}>{run.status}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">{run.job_id}</span>
                  <span className="text-xs text-zinc-500">{when(run.created_at)}</span>
                  {canResume(run) && <span className="text-xs text-amber-300">retryable</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="jm-panel p-4" aria-label="Run detail">
          <h3 className={HEADING}>Step timeline</h3>
          <div className="mt-2">
            {selected ? (
              <RunDetail
                run={selected}
                busy={busy}
                onRetry={(step) =>
                  void act(() => retryPipelineRun(selected.id, step), step ? `Rerunning from ${step}.` : "Retry queued.")
                }
                onCancel={() => {
                  if (window.confirm("Cancel this run? Its running agent process is killed and nothing more is written.")) {
                    void act(() => cancelPipelineRun(selected.id), "Run cancelled.");
                  }
                }}
              />
            ) : (
              <p className="text-sm text-zinc-500">Pick a run to see each step and its attempts.</p>
            )}
          </div>
        </div>
      </section>

      <section className="jm-panel p-4" aria-label="Stats">
        <h3 className={HEADING}>
          <Activity className="h-4 w-4 text-teal-300" aria-hidden /> Stats per step and adapter
        </h3>
        {stats && Object.keys(stats.runs).length > 0 && (
          <p className="mt-2 text-xs text-zinc-400">
            Runs:{" "}
            {Object.entries(stats.runs)
              .map(([status, count]) => `${count} ${status}`)
              .join(", ")}
          </p>
        )}
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="pb-1 pr-2 font-medium">Step</th>
                <th className="pb-1 pr-2 font-medium">Adapter</th>
                <th className="pb-1 pr-2 font-medium">Attempts</th>
                <th className="pb-1 pr-2 font-medium">Pass rate</th>
                <th className="pb-1 pr-2 font-medium">p50</th>
                <th className="pb-1 pr-2 font-medium">p90</th>
                <th className="pb-1 pr-2 font-medium">Cost</th>
                <th className="pb-1 font-medium">Last error</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800 text-zinc-300">
              {(stats?.steps ?? []).map((row) => (
                <tr key={`${row.step}:${row.adapter}`}>
                  <td className="py-1.5 pr-2 text-zinc-100">{row.step}</td>
                  <td className="py-1.5 pr-2">{row.adapter}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{row.attempts}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{Math.round(row.pass_rate * 100)}%</td>
                  <td className="py-1.5 pr-2 tabular-nums">{formatMs(row.p50_ms)}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{formatMs(row.p90_ms)}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{formatCost(row.cost)}</td>
                  <td className="max-w-[18rem] truncate py-1.5 text-xs text-zinc-500" title={row.last_error}>
                    {row.last_error}
                  </td>
                </tr>
              ))}
              {stats && stats.steps.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-3 text-zinc-500">
                    No attempts recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {stats && stats.models.length > 0 && (
          <>
            <h4 className="jm-section-title mt-4">Per model</h4>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-zinc-800 text-zinc-300">
                {stats.models.map((row) => (
                  <tr key={row.model}>
                    <td className="py-1.5 pr-2 text-zinc-100">{row.model}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{row.attempts} attempts</td>
                    <td className="py-1.5 pr-2 tabular-nums">{Math.round(row.pass_rate * 100)}% ok</td>
                    <td className="py-1.5 pr-2 tabular-nums">p50 {formatMs(row.p50_ms)}</td>
                    <td className="py-1.5 pr-2 tabular-nums">p90 {formatMs(row.p90_ms)}</td>
                    <td className="py-1.5 tabular-nums">{formatCost(row.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="jm-panel p-4" aria-label="Adapter health">
        <h3 className={HEADING}>Adapter health</h3>
        <ul className="mt-2 divide-y divide-zinc-800">
          {adapters.map((adapter) => (
            <li key={adapter.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
              <span className="w-40 shrink-0 font-medium text-zinc-100">{adapter.name}</span>
              <span className="w-16 text-xs text-zinc-500">{adapter.enabled ? "on" : "off"}</span>
              <span className={`text-xs ${adapter.health.healthy ? "text-teal-300" : "text-rose-300"}`}>
                {adapter.health.healthy ? "healthy" : adapter.health.reason || "unhealthy"}
              </span>
              {adapter.health.until && <span className="text-xs text-zinc-500">until {when(adapter.health.until)}</span>}
              <span className="ml-auto text-xs text-zinc-500">
                {adapter.capabilities.join(", ")} · max {adapter.max_parallel}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
