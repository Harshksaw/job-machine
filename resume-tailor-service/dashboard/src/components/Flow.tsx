import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, GitFork, RefreshCw } from "lucide-react";
import { ApiError, PipelineError, getPipelineFunnel } from "../api";
import { flowSteps, presetRange, visibleRows, type RangePreset } from "../lib/flow";
import type { FunnelNode, PipelineFunnel } from "../types";

const HEADING = "flex items-center gap-2 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100";

function errorText(error: unknown): string {
  if (error instanceof PipelineError) return error.lines.join("; ");
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Failed to load the flow counts.";
}

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function kindTone(node: FunnelNode): string {
  if (node.kind === "source") return "font-medium text-zinc-50";
  if (node.kind === "tier") return "text-zinc-100";
  if (node.kind === "dropped" || node.kind === "reason") return "text-rose-200";
  if (node.kind === "job") return "text-zinc-300";
  return "text-zinc-200";
}

function Extra({ node }: { node: FunnelNode }) {
  const bits: string[] = [];
  if (node.fetched !== undefined) bits.push(`${node.fetched} fetched`);
  if (node.dropped) bits.push(`${node.dropped} dropped`);
  if (node.kept !== undefined) bits.push(`${node.kept} kept by harvest`);
  if (node.provisional) bits.push("tier guessed from location");
  if (node.job) {
    bits.push(node.job.fit_score !== null ? `fit ${node.job.fit_score}` : "not scored");
    bits.push(node.job.status);
  }
  return bits.length ? <span className="text-xs text-zinc-500">{bits.join(" · ")}</span> : null;
}

export default function Flow({ onOpenDossier }: { onOpenDossier: (jobId: string) => void }) {
  const [funnel, setFunnel] = useState<PipelineFunnel | null>(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFunnel(await getPipelineFunnel(since, until));
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [since, until]);

  useEffect(() => {
    void load();
  }, [load]);

  const steps = useMemo(() => (funnel ? flowSteps(funnel) : []), [funnel]);
  const rows = useMemo(() => (funnel ? visibleRows(funnel.tree, expanded) : []), [funnel, expanded]);

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const preset = (value: RangePreset) => {
    const range = presetRange(value);
    setSince(range.since);
    setUntil(range.until);
  };

  return (
    <div className="h-full space-y-4 overflow-y-auto pb-6">
      <section className="jm-panel flex flex-wrap items-end gap-3 p-4" aria-label="Date range">
        <label className="text-xs text-zinc-400">
          From
          <input
            type="date"
            className="jm-input mt-1 h-8 w-40 py-0 text-xs"
            value={since}
            onChange={(event) => setSince(event.target.value)}
          />
        </label>
        <label className="text-xs text-zinc-400">
          Until (not included)
          <input
            type="date"
            className="jm-input mt-1 h-8 w-40 py-0 text-xs"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
          />
        </label>
        <div className="flex gap-1">
          <button type="button" className="jm-btn-ghost h-8 px-2 text-xs" onClick={() => preset("7d")}>
            Last 7 days
          </button>
          <button type="button" className="jm-btn-ghost h-8 px-2 text-xs" onClick={() => preset("30d")}>
            Last 30 days
          </button>
          <button type="button" className="jm-btn-ghost h-8 px-2 text-xs" onClick={() => preset("all")}>
            All time
          </button>
        </div>
        <button type="button" className="jm-btn-secondary ml-auto h-8 px-3 text-xs" onClick={() => void load()}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} aria-hidden /> Refresh
        </button>
        <p className="w-full text-xs text-zinc-500">
          {since || until
            ? "Showing listings created or moved in this range, at the stage they are in now."
            : "Showing every listing at the stage it is in now."}
          {funnel?.harvest?.run_at && ` Last harvest ${when(funnel.harvest.run_at)}.`}
        </p>
      </section>

      {error && <p className="rounded-md border border-rose-900 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">{error}</p>}

      <section className="jm-panel p-4" aria-label="How the flow works">
        <h3 className={HEADING}>
          <GitFork className="h-4 w-4 text-teal-300" aria-hidden /> How a listing moves
        </h3>
        <p className="mt-2 text-sm text-zinc-400">
          Each box is one step, top to bottom. The big number is how many listings sit at that step right now.
        </p>
        <ol className="mx-auto mt-3 flex max-w-2xl flex-col items-stretch">
          {steps.map((step, index) => (
            <Fragment key={step.key}>
              {index > 0 && (
                <li aria-hidden className="flex justify-center py-1 text-zinc-600">
                  <ChevronDown className="h-4 w-4" />
                </li>
              )}
              <li className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-4 py-3">
                <div className="flex items-baseline gap-3">
                  <span className="text-sm font-semibold text-zinc-50">{step.title}</span>
                  <span className="ml-auto text-xl font-semibold tabular-nums text-teal-200">{step.count}</span>
                </div>
                <p className="mt-1 text-xs text-zinc-400">{step.explain}</p>
                <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-300">
                  {step.parts.map((part) => (
                    <li key={part.label}>
                      {part.label} <span className="tabular-nums text-zinc-50">{part.count}</span>
                    </li>
                  ))}
                </ul>
              </li>
            </Fragment>
          ))}
        </ol>
      </section>

      <section className="jm-panel p-4" aria-label="Counts by source">
        <h3 className={HEADING}>Counts by source, region and stage</h3>
        <p className="mt-2 text-xs text-zinc-500">
          Click a row to open it. Under each stage are its top jobs by fit; click one to open the dossier.
        </p>
        <table className="mt-2 w-full text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              <th className="pb-1 pr-2 font-medium">Source, region, stage, job</th>
              <th className="pb-1 text-right font-medium">Count</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {rows.length === 0 && (
              <tr>
                <td colSpan={2} className="py-3 text-zinc-500">
                  {funnel ? "No listings in this range." : "Loading."}
                </td>
              </tr>
            )}
            {rows.map((row) => {
              const { node } = row;
              const link = node.kind === "job" && node.job?.dossier;
              const onClick = row.hasChildren
                ? () => toggle(row.id)
                : link
                  ? () => onOpenDossier(node.job!.id)
                  : undefined;
              return (
                <tr key={row.id} className={onClick ? "cursor-pointer hover:bg-zinc-900" : ""} onClick={onClick}>
                  <td className="py-1.5 pr-2">
                    <div className="flex flex-wrap items-center gap-x-2" style={{ paddingLeft: `${row.depth * 1.25}rem` }}>
                      {row.hasChildren ? (
                        <button
                          type="button"
                          className="text-zinc-500"
                          aria-expanded={row.expanded}
                          aria-label={`${row.expanded ? "Collapse" : "Expand"} ${node.label}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggle(row.id);
                          }}
                        >
                          {row.expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                        </button>
                      ) : (
                        <span className="inline-block w-3.5" aria-hidden />
                      )}
                      {link ? (
                        <button
                          type="button"
                          className="text-left text-teal-200 underline-offset-2 hover:underline"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenDossier(node.job!.id);
                          }}
                        >
                          {node.label}
                        </button>
                      ) : (
                        <span className={kindTone(node)}>{node.label}</span>
                      )}
                      <Extra node={node} />
                    </div>
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-zinc-100">{node.kind === "job" ? "" : node.count}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
