import { useCallback, useEffect, useState } from "react";
import { Activity, BarChart3, Plug, RefreshCw, Wallet } from "lucide-react";
import {
  checkConnection,
  getSystemStats,
  getTelemetry,
  listConnections,
  type ConnectionInfo,
  type ConnectionResult,
  type SystemStats,
  type TelemetrySummary,
} from "../api";
import AgentsSettings from "./AgentsSettings";

const STATUS_STYLE: Record<ConnectionResult["status"], { dot: string; text: string; label: string }> = {
  ok: { dot: "bg-teal-400", text: "text-teal-300", label: "OK" },
  warn: { dot: "bg-amber-400", text: "text-amber-300", label: "Check" },
  fail: { dot: "bg-rose-400", text: "text-rose-300", label: "Down" },
};

const AGENT_STATUS_STYLE = {
  ok: { dot: "bg-teal-400", text: "text-teal-300" },
  blocked: { dot: "bg-rose-400", text: "text-rose-300" },
  idle: { dot: "bg-zinc-600", text: "text-zinc-500" },
} as const;

function percent(rate: number | null): string {
  return rate === null ? "n/a" : `${(rate * 100).toFixed(rate < 0.1 ? 1 : 0)}%`;
}

function ms(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

function when(iso: string | null): string {
  if (!iso) return "never";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="jm-panel px-4 py-3">
      <p className="jm-section-title">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-50">{value}</p>
      {hint && <p className="text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

export default function Settings() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetrySummary | null>(null);
  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [results, setResults] = useState<Record<string, ConnectionResult>>({});
  const [checking, setChecking] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (refresh: boolean) => {
    setLoading(true);
    setMessage(null);
    try {
      const [s, t] = await Promise.all([getSystemStats(refresh), getTelemetry()]);
      setStats(s);
      setTelemetry(t);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  const check = useCallback(async (id: string) => {
    setChecking((current) => new Set(current).add(id));
    let result: ConnectionResult;
    try {
      result = await checkConnection(id);
    } catch (error) {
      result = { id, status: "fail", detail: error instanceof Error ? error.message : "Check failed.", ms: 0 };
    }
    setResults((current) => ({ ...current, [id]: result }));
    setChecking((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  const checkAll = useCallback(
    (items: ConnectionInfo[]) => {
      for (const item of items) void check(item.id);
    },
    [check]
  );

  useEffect(() => {
    void load(false);
    listConnections()
      .then((items) => {
        setConnections(items);
        checkAll(items);
      })
      .catch(() => setMessage("Failed to load connections."));
  }, [load, checkAll]);

  const weeklyMax = Math.max(1, ...(stats?.weekly.map((week) => week.applied) ?? [1]));
  const people = stats?.people ?? {};
  const failing = Object.values(results).filter((result) => result.status !== "ok").length;

  return (
    <div className="h-full space-y-4 overflow-y-auto">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-xs text-zinc-500">
          {stats
            ? `Stats as of ${when(stats.generated_at)} · service up since ${when(stats.service.started_at)} · ${stats.service.database}`
            : "Loading stats..."}
        </p>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={loading}
          className="jm-btn-secondary ml-auto h-8 px-3 text-xs"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden />
          Refresh stats
        </button>
      </div>

      {message && <p className="text-sm text-amber-300">{message}</p>}

      {stats && (
        <>
          <section aria-label="Totals" className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <Tile label="Dossiers" value={stats.totals.dossiers} />
            <Tile label="Applied" value={stats.totals.applied} />
            <Tile
              label="Heard back"
              value={stats.totals.responded}
              hint={`${percent(stats.totals.response_rate)} of applied`}
            />
            <Tile label="Rejected" value={stats.totals.rejected} />
            <Tile label="No answer yet" value={stats.totals.waiting} />
            <Tile label="Fit 8+ not applied" value={stats.backlog.strong_unapplied} />
            <Tile
              label="Outreach sent"
              value={people.sent ?? 0}
              hint={`${people.replied ?? 0} replied · ${people.approved ?? 0} approved, unsent`}
            />
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <div className="jm-panel p-4">
              <h2 className="flex items-center gap-2 mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">
                <BarChart3 className="h-4 w-4 text-teal-300" aria-hidden /> By source
              </h2>
              <table className="mt-3 w-full text-sm tabular-nums">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="pb-1 font-medium">Source</th>
                    <th className="pb-1 text-right font-medium">Applied</th>
                    <th className="pb-1 text-right font-medium">Heard back</th>
                    <th className="pb-1 text-right font-medium">Rate</th>
                    <th className="pb-1 text-right font-medium">Rejected</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800 text-zinc-300">
                  {stats.by_source.map((row) => (
                    <tr key={row.source}>
                      <td className="py-1.5 text-zinc-100">{row.source}</td>
                      <td className="py-1.5 text-right">{row.applied}</td>
                      <td className="py-1.5 text-right">{row.responded}</td>
                      <td className="py-1.5 text-right">{percent(row.response_rate)}</td>
                      <td className="py-1.5 text-right">{row.rejected}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="jm-panel p-4">
              <h2 className="mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">By fit score</h2>
              <table className="mt-3 w-full text-sm tabular-nums">
                <thead className="text-left text-xs text-zinc-500">
                  <tr>
                    <th className="pb-1 font-medium">Fit</th>
                    <th className="pb-1 text-right font-medium">Tracked</th>
                    <th className="pb-1 text-right font-medium">Applied</th>
                    <th className="pb-1 text-right font-medium">Heard back</th>
                    <th className="pb-1 text-right font-medium">Rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800 text-zinc-300">
                  {stats.by_fit.map((row) => (
                    <tr key={row.fit}>
                      <td className="py-1.5 text-zinc-100">{row.fit}</td>
                      <td className="py-1.5 text-right">{row.tracked}</td>
                      <td className="py-1.5 text-right">{row.applied}</td>
                      <td className="py-1.5 text-right">{row.responded}</td>
                      <td className="py-1.5 text-right">{percent(row.response_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="jm-panel p-4">
            <h2 className="mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">Applications per week</h2>
            <ol className="mt-3 flex h-36 items-end gap-2" aria-label="Applications per week, last 12 weeks">
              {stats.weekly.map((week) => (
                <li key={week.week} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1">
                  <span className="text-xs tabular-nums text-zinc-400">{week.applied || ""}</span>
                  <span
                    className="w-full rounded-t bg-teal-600"
                    style={{ height: `${(week.applied / weeklyMax) * 100}%`, minHeight: week.applied ? 2 : 0 }}
                    title={`Week of ${week.week}: ${week.applied} applied`}
                  />
                  <span className="truncate text-[10px] tabular-nums text-zinc-500">{week.week.slice(5)}</span>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}

      <section className="jm-panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="flex items-center gap-2 mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">
            <Plug className="h-4 w-4 text-teal-300" aria-hidden /> Connections
          </h2>
          <p className="text-xs text-zinc-500">
            {checking.size > 0
              ? `Checking ${checking.size}...`
              : failing > 0
                ? `${failing} need attention`
                : "All checks pass"}
          </p>
          <button
            type="button"
            onClick={() => checkAll(connections)}
            disabled={checking.size > 0}
            className="jm-btn-secondary ml-auto h-8 px-3 text-xs"
          >
            Check all
          </button>
        </div>
        <ul className="mt-3 divide-y divide-zinc-800">
          {connections.map((item) => {
            const result = results[item.id];
            const busy = checking.has(item.id);
            const style = result ? STATUS_STYLE[result.status] : null;
            return (
              <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 text-sm">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${busy || !style ? "bg-zinc-600" : style.dot}`}
                  aria-hidden
                />
                <span className="w-40 shrink-0 font-medium text-zinc-100">{item.label}</span>
                <span className="min-w-0 flex-1 text-zinc-400">
                  {busy ? (
                    "Checking..."
                  ) : result ? (
                    <>
                      <span className={`font-medium ${style?.text}`}>{style?.label}</span>
                      {" · "}
                      {result.detail}
                      <span className="text-zinc-600"> · {ms(result.ms)}</span>
                    </>
                  ) : (
                    item.what
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => void check(item.id)}
                  disabled={busy}
                  title={item.what}
                  className="jm-btn-ghost h-7 px-2 text-xs"
                >
                  Check
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <AgentsSettings />

      {telemetry && (
        <section className="jm-panel p-4">
          <h2 className="flex items-center gap-2 mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">
            <Activity className="h-4 w-4 text-teal-300" aria-hidden /> Telemetry
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            {telemetry.enabled
              ? `OpenTelemetry tracing is on as "${telemetry.service}". ${telemetry.buffered} of ${telemetry.buffer_size} spans kept since ${when(telemetry.since)}. `
              : "OpenTelemetry tracing is off (OTEL_SDK_DISABLED). "}
            {telemetry.exporter
              ? `Exporting to ${telemetry.exporter}.`
              : "Not exported: set OTEL_EXPORTER_OTLP_ENDPOINT in resume-tailor-service/.env and restart to send traces to a collector."}
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead className="text-left text-xs text-zinc-500">
                <tr>
                  <th className="pb-1 font-medium">Route or call</th>
                  <th className="pb-1 text-right font-medium">Count</th>
                  <th className="pb-1 text-right font-medium">Errors</th>
                  <th className="pb-1 text-right font-medium">p50</th>
                  <th className="pb-1 text-right font-medium">p95</th>
                  <th className="pb-1 text-right font-medium">Max</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800 text-zinc-300">
                {telemetry.routes.map((row) => (
                  <tr key={`${row.kind}:${row.name}`}>
                    <td className="py-1.5 font-mono text-xs text-zinc-100">{row.name}</td>
                    <td className="py-1.5 text-right">{row.count}</td>
                    <td className={`py-1.5 text-right ${row.errors ? "text-rose-300" : ""}`}>{row.errors}</td>
                    <td className="py-1.5 text-right">{ms(row.p50_ms)}</td>
                    <td className="py-1.5 text-right">{ms(row.p95_ms)}</td>
                    <td className="py-1.5 text-right">{ms(row.max_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {telemetry.recent_errors.length > 0 && (
            <div className="mt-3">
              <p className="jm-section-title">Recent errors</p>
              <ul className="mt-1 space-y-0.5 text-xs text-zinc-400">
                {telemetry.recent_errors.map((span) => (
                  <li key={`${span.trace_id}:${span.name}:${span.started_at}`}>
                    {when(span.started_at)} · <span className="font-mono text-rose-300">{span.name}</span>
                    {span.status ? ` · HTTP ${span.status}` : ""} · {ms(span.duration_ms)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {stats?.ai_usage && (
        <section className="jm-panel p-4">
          <h2 className="flex items-center gap-2 mb-3 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100">
            <Wallet className="h-4 w-4 text-teal-300" aria-hidden /> AI spend (CAD)
          </h2>
          <p className="mt-1 text-xs text-zinc-500">From the usage meter, refreshed {when(stats.ai_usage.generated_at)}.</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            {(stats.ai_usage.agents ?? []).map((agent) => {
              const style = AGENT_STATUS_STYLE[agent.status];
              return (
                <div key={agent.tool} className="rounded-md border border-zinc-800 p-2.5">
                  <div className="flex items-center gap-2 text-sm text-zinc-100">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${style.dot}`} aria-hidden />
                    {agent.tool}
                    <span className={`ml-auto text-xs ${style.text}`}>{agent.label}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-zinc-500" title={agent.detail}>
                    {agent.detail || "Start a run to see its status"}
                  </p>
                  {agent.at && <p className="text-xs text-zinc-600">as of {when(agent.at)}</p>}
                </div>
              );
            })}
          </div>
          <table className="mt-3 w-full text-sm tabular-nums">
            <thead className="text-left text-xs text-zinc-500">
              <tr>
                <th className="pb-1 font-medium">Tool</th>
                <th className="pb-1 text-right font-medium">Today</th>
                <th className="pb-1 text-right font-medium">Day budget</th>
                <th className="pb-1 text-right font-medium">This week</th>
                <th className="pb-1 text-right font-medium">Week budget</th>
                <th className="pb-1 text-right font-medium">Calls today</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800 text-zinc-300">
              {stats.ai_usage.providers.map((row) => (
                <tr key={row.provider}>
                  <td className="py-1.5 text-zinc-100">{row.provider}</td>
                  <td className="py-1.5 text-right">{row.day.toFixed(2)}</td>
                  <td className="py-1.5 text-right">{row.day_budget ?? "none"}</td>
                  <td
                    className={`py-1.5 text-right ${
                      row.week_budget && row.week >= row.week_budget * 0.8 ? "text-amber-300" : ""
                    }`}
                  >
                    {row.week.toFixed(2)}
                    {row.week_budget ? (
                      <div className="ml-auto mt-1 h-1 w-20 rounded bg-zinc-800" aria-hidden>
                        <div
                          className={`h-1 rounded ${row.week >= row.week_budget * 0.8 ? "bg-amber-400" : "bg-teal-400"}`}
                          style={{ width: `${Math.min(100, (row.week / row.week_budget) * 100)}%` }}
                        />
                      </div>
                    ) : null}
                  </td>
                  <td className="py-1.5 text-right">{row.week_budget ?? "none"}</td>
                  <td className="py-1.5 text-right">{row.calls_day}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
