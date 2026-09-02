import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BriefcaseBusiness,
  FileText,
  Import,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Star,
} from "lucide-react";
import type {
  JobSummary,
  JobWorkspace as JobWorkspaceType,
  JobWorkspaceInput,
} from "../types";
import {
  createJob,
  getJob,
  importJobsFromSheet,
  listJobs,
} from "../api";
import {
  fitTone,
  formatJobDate,
  JOB_STATUSES,
  JOB_STATUS_LABEL,
  JOB_STATUS_STYLE,
} from "../lib/jobs";
import JobDetail from "./JobDetail";
import JobForm from "./JobForm";

interface Props {
  focusJobId?: string | null;
  onFocusConsumed?: () => void;
  onPeopleChanged?: () => void;
}

export default function JobWorkspace({
  focusJobId = null,
  onFocusConsumed,
  onPeopleChanged,
}: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(focusJobId);
  const [selected, setSelected] = useState<JobWorkspaceType | null>(null);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("active");
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState("");
  const [detailDirty, setDetailDirty] = useState(false);

  const loadList = useCallback(async () => {
    try {
      const next = await listJobs();
      setJobs(next);
      setPhase("ready");
      setError("");
      setSelectedId((current) => {
        if (current && next.some((job) => job.id === current)) return current;
        return next[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job dossiers.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (!focusJobId || !jobs.some((job) => job.id === focusJobId)) return;
    setSelectedId(focusJobId);
    onFocusConsumed?.();
  }, [focusJobId, jobs, onFocusConsumed]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getJob(selectedId)
      .then((job) => {
        if (cancelled) return;
        setSelected(job);
        setDetailLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load dossier.");
        setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const shown = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return jobs.filter((job) => {
      if (
        normalized &&
        !job.company.toLowerCase().includes(normalized) &&
        !job.role.toLowerCase().includes(normalized) &&
        !job.source.toLowerCase().includes(normalized) &&
        !job.location.toLowerCase().includes(normalized) &&
        !job.next_action.toLowerCase().includes(normalized)
      ) {
        return false;
      }
      if (status === "all") return true;
      if (status === "active") {
        return !["rejected", "skipped", "archived"].includes(job.status);
      }
      return job.status === status;
    });
  }, [jobs, query, status]);

  const choose = (jobId: string) => {
    if (jobId === selectedId) return;
    if (detailDirty && !window.confirm("Discard unsaved dossier changes?")) return;
    setDetailDirty(false);
    setSelectedId(jobId);
  };

  const created = async (body: JobWorkspaceInput) => {
    const job = await createJob(body, "Manual");
    setAdding(false);
    setSelected(job);
    setSelectedId(job.id);
    await loadList();
  };

  const imported = async () => {
    setImporting(true);
    setNotice("");
    setError("");
    try {
      const result = await importJobsFromSheet();
      setNotice(
        `${result.imported_rows} rows imported · ${result.created_jobs} new · ${result.updated_jobs} updated`
      );
      await loadList();
      if (!selectedId && result.job_ids[0]) setSelectedId(result.job_ids[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sheet import failed.");
    } finally {
      setImporting(false);
    }
  };

  const updated = (job: JobWorkspaceType) => {
    setSelected(job);
    setDetailDirty(false);
    void loadList();
  };

  const deleted = async (jobId: string) => {
    setSelected(null);
    setSelectedId(null);
    setDetailDirty(false);
    const remaining = jobs.filter((job) => job.id !== jobId);
    setJobs(remaining);
    setSelectedId(remaining[0]?.id ?? null);
    await loadList();
  };

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col overflow-hidden rounded-lg border border-zinc-700 bg-canvas">
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-700 bg-surface px-3 py-3">
        <div className="relative min-w-[190px] flex-1 sm:max-w-xs">
          <label htmlFor="dossier-search" className="visually-hidden">Search dossiers</label>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" aria-hidden />
          <input
            id="dossier-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search dossiers"
            className="jm-input pl-9"
          />
        </div>
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="jm-input w-auto"
        >
          <option value="active">Active</option>
          <option value="all">All statuses</option>
          {JOB_STATUSES.map((jobStatus) => (
            <option key={jobStatus} value={jobStatus}>
              {JOB_STATUS_LABEL[jobStatus]}
            </option>
          ))}
        </select>
        <span className="text-sm text-zinc-400">
          {shown.length} of {jobs.length}
        </span>
        <button
          type="button"
          onClick={() => void imported()}
          disabled={importing}
          className="jm-btn-secondary h-10"
          title="Import Google Sheet"
        >
          {importing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Import className="h-3.5 w-3.5" />
          )}
          Import
        </button>
        <button
          type="button"
          onClick={() => void loadList()}
          className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100"
          aria-label="Refresh dossiers"
          title="Refresh"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="jm-btn-primary"
        >
          <Plus className="h-3.5 w-3.5" />
          New job
        </button>
      </div>

      {(error || notice) && (
        <div
          className={`flex items-center gap-2 border-b px-3 py-2 text-xs ${
            error
              ? "border-rose-900/60 bg-rose-950/20 text-rose-300"
              : "border-teal-900/60 bg-teal-950/20 text-teal-300"
          }`}
        >
          {error && <AlertTriangle className="h-3.5 w-3.5" />}
          {error || notice}
        </div>
      )}

      {phase === "loading" ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading dossiers...
        </div>
      ) : jobs.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-24 text-center">
          <BriefcaseBusiness className="h-9 w-9 text-zinc-700" />
          <h2 className="text-sm font-semibold text-zinc-300">No job dossiers</h2>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void imported()}
              disabled={importing}
              className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              <Import className="h-4 w-4" />
              Import sheet
            </button>
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-500"
            >
              <Plus className="h-4 w-4" />
              New job
            </button>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(12rem,38vh)_minmax(0,1fr)] lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:grid-rows-1">
          <aside className="min-h-0 overflow-y-auto border-b border-zinc-700 bg-surface lg:border-b-0 lg:border-r">
            {shown.length === 0 ? (
              <div className="p-6 text-center text-sm text-zinc-600">
                No matching dossiers.
              </div>
            ) : (
              <div className="divide-y divide-zinc-800">
                {shown.map((job) => {
                  const statusClass =
                    JOB_STATUS_STYLE[job.status] ??
                    "border-zinc-700 bg-zinc-900 text-zinc-400";
                  const priority = job.priority === "dream" || job.priority === "high";
                  return (
                    <button
                      key={job.id}
                      type="button"
                      onClick={() => choose(job.id)}
                      aria-current={selectedId === job.id ? "true" : undefined}
                      className={`w-full px-4 py-3.5 text-left transition ${
                        selectedId === job.id
                          ? "bg-teal-950/40 shadow-[inset_3px_0_0_#2dd4bf]"
                          : "hover:bg-raised"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-base font-semibold text-zinc-100">
                              {job.company}
                            </span>
                            {priority && (
                              <Star
                                className="h-4 w-4 shrink-0 text-amber-300"
                                fill="currentColor"
                                aria-label="High priority"
                              />
                            )}
                          </div>
                          <div className="mt-0.5 truncate text-sm text-zinc-300">
                            {job.role}
                          </div>
                        </div>
                        <span
                          className={`jm-badge shrink-0 ${fitTone(
                            job.fit_score
                          )}`}
                        >
                          Fit {job.fit_score ?? "—"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span
                          className={`jm-badge ${statusClass}`}
                        >
                          {JOB_STATUS_LABEL[job.status] ?? job.status}
                        </span>
                        {job.tailored_resume_id && (
                          <span className="jm-badge border-teal-700 text-teal-100">
                            <FileText className="h-3 w-3" aria-hidden /> PDF
                          </span>
                        )}
                        <time className="ml-auto text-xs text-zinc-400">
                          {formatJobDate(job.updated_at)}
                        </time>
                      </div>
                      {job.next_action && (
                        <div className="mt-2 line-clamp-2 text-sm text-zinc-200">
                          {job.next_action}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </aside>

          <section className="min-h-0 overflow-hidden">
            {detailLoading ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading dossier...
              </div>
            ) : selected ? (
              <JobDetail
                job={selected}
                onUpdated={updated}
                onDeleted={(jobId) => void deleted(jobId)}
                onDirtyChange={setDetailDirty}
                onPeopleChanged={onPeopleChanged}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-zinc-600">
                Select a dossier.
              </div>
            )}
          </section>
        </div>
      )}

      {adding && <JobForm onCancel={() => setAdding(false)} onSave={created} />}
    </div>
  );
}
