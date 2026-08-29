import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Clock3,
  ExternalLink,
  FileText,
  Inbox as InboxIcon,
  Loader2,
  Pause,
  RefreshCw,
  Search,
  Send,
  Users,
} from "lucide-react";
import type { JobDecision, JobSummary, JobWorkspace } from "../types";
import { decideJob, getJob, listJobs } from "../api";
import JobPeople from "./JobPeople";
import {
  countByStatus,
  fitTone,
  formatJobDate,
  INBOX_QUEUE_LABEL,
  INBOX_QUEUES,
  inInboxQueue,
  JOB_STATUS_LABEL,
  JOB_STATUS_STYLE,
  sortInbox,
  type InboxQueue,
} from "../lib/jobs";
import { safeHref } from "../lib/people";

const PROGRESS_STATUSES = [
  "discovered",
  "researching",
  "ready",
  "applying",
  "applied",
  "outreach",
  "interview",
] as const;

interface Props {
  onOpenDossier: (jobId: string) => void;
  onPeopleChanged?: () => void;
}

export default function Inbox({ onOpenDossier, onPeopleChanged }: Props) {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [queue, setQueue] = useState<InboxQueue>("decide");
  const [minFit, setMinFit] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [ticket, setTicket] = useState<JobWorkspace | null>(null);
  const [ticketLoading, setTicketLoading] = useState(false);
  const [busy, setBusy] = useState<JobDecision | null>(null);
  const [notice, setNotice] = useState("");

  const loadList = useCallback(async (silent = false) => {
    if (!silent) setPhase("loading");
    try {
      const next = await listJobs();
      setJobs(next);
      setPhase("ready");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void loadList();
    const timer = window.setInterval(() => void loadList(true), 15000);
    return () => window.clearInterval(timer);
  }, [loadList]);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const match = hash.match(/^inbox\/([a-f0-9]{8,})$/i);
    if (match) setSelectedId(match[1]);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setTicket(null);
      if (window.location.hash.startsWith("#inbox/")) {
        window.history.replaceState(null, "", "#inbox");
      }
      return;
    }
    window.history.replaceState(null, "", `#inbox/${selectedId}`);
    let cancelled = false;
    setTicketLoading(true);
    getJob(selectedId)
      .then((job) => {
        if (!cancelled) {
          setTicket(job);
          setTicketLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load ticket.");
          setTicketLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const counts = useMemo(() => countByStatus(jobs), [jobs]);
  const queueCounts = useMemo(() => {
    const next: Record<InboxQueue, number> = {
      decide: 0,
      ready: 0,
      applied: 0,
      "needs-you": 0,
      all: 0,
    };
    for (const job of jobs) {
      for (const key of INBOX_QUEUES) {
        if (inInboxQueue(job, key)) next[key] += 1;
      }
    }
    return next;
  }, [jobs]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = jobs.filter((job) => {
      if (!inInboxQueue(job, queue)) return false;
      if (minFit != null && (job.fit_score ?? 0) < minFit) return false;
      if (!q) return true;
      return (
        job.company.toLowerCase().includes(q) ||
        job.role.toLowerCase().includes(q) ||
        job.location.toLowerCase().includes(q) ||
        job.work_mode.toLowerCase().includes(q) ||
        job.source.toLowerCase().includes(q) ||
        job.notes.toLowerCase().includes(q) ||
        job.next_action.toLowerCase().includes(q)
      );
    });
    return sortInbox(filtered);
  }, [jobs, queue, minFit, query]);

  const decide = async (decision: JobDecision) => {
    if (!ticket) return;
    setBusy(decision);
    setError("");
    setNotice("");
    try {
      const updated = await decideJob(ticket.id, decision);
      setTicket(updated);
      setNotice(
        decision === "approve"
          ? `Approved ${updated.company} — queued to apply.`
          : decision === "hold"
            ? `Held ${updated.company} for later review.`
            : `Marked ${updated.company} applied.`
      );
      await loadList(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save decision.");
    } finally {
      setBusy(null);
    }
  };

  const peopleChanged = () => {
    onPeopleChanged?.();
    void loadList(true);
  };

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950">
      <div className="grid grid-cols-2 gap-px border-b border-zinc-800 bg-zinc-800 sm:grid-cols-4 lg:grid-cols-7">
        {PROGRESS_STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            onClick={() =>
              setQueue(
                status === "discovered" || status === "researching"
                  ? "decide"
                  : status === "ready" || status === "applying"
                    ? "ready"
                    : "applied"
              )
            }
            className="bg-zinc-950 px-3 py-2.5 text-left hover:bg-zinc-900"
          >
            <div className="text-[10px] uppercase tracking-wide text-zinc-500">
              {JOB_STATUS_LABEL[status]}
            </div>
            <div className="text-lg font-semibold tabular-nums text-zinc-100">
              {counts[status] ?? 0}
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-900/70 px-3 py-2.5">
        <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tickets"
            className="w-full rounded-md border border-zinc-700 bg-zinc-950 py-1.5 pl-8 pr-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-teal-500 focus:outline-none"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {INBOX_QUEUES.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setQueue(key)}
              className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${
                queue === key
                  ? "bg-teal-700 text-white"
                  : "border border-zinc-800 text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {INBOX_QUEUE_LABEL[key]}
              <span className="ml-1.5 tabular-nums text-zinc-300">
                {queueCounts[key]}
              </span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setMinFit(minFit === 8 ? null : 8)}
          className={`rounded-md px-2.5 py-1.5 text-xs font-medium ${
            minFit === 8
              ? "bg-emerald-800 text-emerald-100"
              : "border border-zinc-800 text-zinc-400 hover:text-zinc-100"
          }`}
        >
          Fit 8+
        </button>
        <span className="ml-auto text-xs text-zinc-600">
          {shown.length} tickets
        </span>
        <button
          type="button"
          onClick={() => void loadList()}
          className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100"
          aria-label="Refresh inbox"
        >
          <RefreshCw className="h-4 w-4" />
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
          Loading tickets...
        </div>
      ) : phase === "error" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-zinc-400">
          <AlertTriangle className="h-6 w-6 text-rose-400" />
          {error}
          <button
            type="button"
            onClick={() => void loadList()}
            className="rounded-md border border-zinc-700 px-3 py-1.5 text-zinc-200"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 lg:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="min-h-0 overflow-y-auto border-b border-zinc-800 lg:border-b-0 lg:border-r">
            {shown.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-6 py-16 text-center text-sm text-zinc-600">
                <InboxIcon className="h-8 w-8" />
                No tickets in this queue.
              </div>
            ) : (
              <div className="divide-y divide-zinc-800">
                {shown.map((job) => (
                  <TicketRow
                    key={job.id}
                    job={job}
                    selected={job.id === selectedId}
                    onSelect={() => setSelectedId(job.id)}
                  />
                ))}
              </div>
            )}
          </aside>

          <section className="min-h-0 overflow-y-auto">
            {ticketLoading ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Opening ticket...
              </div>
            ) : ticket ? (
              <TicketDetail
                job={ticket}
                busy={busy}
                onDecide={(decision) => void decide(decision)}
                onOpenDossier={() => onOpenDossier(ticket.id)}
                onPeopleChanged={peopleChanged}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-zinc-600">
                <InboxIcon className="h-8 w-8" />
                Pick a ticket. Approve it to apply, or hold it for later.
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function TicketRow({
  job,
  selected,
  onSelect,
}: {
  job: JobSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const statusClass =
    JOB_STATUS_STYLE[job.status] ?? "border-zinc-700 bg-zinc-900 text-zinc-400";
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full px-3 py-3 text-left transition ${
        selected
          ? "bg-teal-950/30 shadow-[inset_3px_0_0_rgb(45,212,191)]"
          : "hover:bg-zinc-800/60"
      }`}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-zinc-100">
            {job.company}
          </div>
          <div className="mt-0.5 truncate text-xs text-zinc-500">{job.role}</div>
        </div>
        <span
          className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-semibold ${fitTone(
            job.fit_score
          )}`}
        >
          {job.fit_score ?? "—"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className={`rounded-md border px-1.5 py-0.5 text-[10px] ${statusClass}`}>
          {JOB_STATUS_LABEL[job.status] ?? job.status}
        </span>
        {job.source && (
          <span className="truncate text-[10px] text-zinc-600">{job.source}</span>
        )}
        {job.has_cover_letter && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-teal-500">
            <FileText className="h-3 w-3" /> kit
          </span>
        )}
        {job.person_count > 0 ? (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-cyan-400">
            <Users className="h-3 w-3" />
            {job.person_count}
          </span>
        ) : (job.fit_score ?? 0) >= 8 ? (
          <span className="text-[10px] text-amber-500">add people</span>
        ) : null}
        {job.needs_user_input && (
          <span className="text-[10px] text-amber-400">needs you</span>
        )}
        <time className="ml-auto text-[10px] text-zinc-700">
          {formatJobDate(job.updated_at)}
        </time>
      </div>
      {(job.location || job.next_action) && (
        <div className="mt-1.5 truncate text-[11px] text-zinc-500">
          {[job.location, job.next_action].filter(Boolean).join(" · ")}
        </div>
      )}
    </button>
  );
}

function TicketDetail({
  job,
  busy,
  onDecide,
  onOpenDossier,
  onPeopleChanged,
}: {
  job: JobWorkspace;
  busy: JobDecision | null;
  onDecide: (decision: JobDecision) => void;
  onOpenDossier: () => void;
  onPeopleChanged: () => void;
}) {
  const listing = safeHref(job.job_url);
  const analysis = job.fit_analysis;
  const blocked = job.application_answers.filter((answer) => answer.needs_user_input);
  const canApprove = job.status === "discovered" || job.status === "researching";
  const canMarkApplied = job.status === "ready" || job.status === "applying";

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-zinc-800 px-4 py-4 lg:px-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-zinc-100">{job.company}</h2>
            <p className="text-sm text-zinc-400">{job.role}</p>
            <p className="mt-1 text-xs text-zinc-600">
              {[job.location, job.work_mode, job.source, job.compensation]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <span
            className={`rounded-md border px-2 py-1 text-sm font-semibold ${fitTone(
              job.fit_score
            )}`}
          >
            {job.fit_score == null ? "Fit —" : `Fit ${job.fit_score}/10`}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {canApprove && (
            <>
              <button
                type="button"
                onClick={() => onDecide("approve")}
                disabled={busy !== null}
                className="inline-flex h-9 items-center gap-1.5 rounded-md bg-teal-600 px-3 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-40"
              >
                {busy === "approve" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                Approve to apply
              </button>
              <button
                type="button"
                onClick={() => onDecide("hold")}
                disabled={busy !== null}
                className="inline-flex h-9 items-center gap-1.5 rounded-md border border-zinc-700 px-3 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
              >
                {busy === "hold" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Pause className="h-4 w-4" />
                )}
                Hold
              </button>
            </>
          )}
          {canMarkApplied && (
            <button
              type="button"
              onClick={() => onDecide("applied")}
              disabled={busy !== null}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-zinc-700 px-3 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
            >
              {busy === "applied" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Mark applied
            </button>
          )}
          {listing && (
            <a
              href={listing}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-zinc-700 px-3 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              <ExternalLink className="h-4 w-4" />
              Open listing
            </a>
          )}
          <button
            type="button"
            onClick={onOpenDossier}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-zinc-700 px-3 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Full dossier
          </button>
        </div>
      </header>

      <div className="space-y-6 px-4 py-5 lg:px-6">
        {job.next_action && (
          <p className="flex items-start gap-2 text-sm text-amber-200/90">
            <Clock3 className="mt-0.5 h-4 w-4 shrink-0" />
            {job.next_action}
          </p>
        )}

        {blocked.length > 0 && (
          <section className="rounded-md border border-amber-900/60 bg-amber-950/20 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-400">
              Needs your input
            </h3>
            <ul className="mt-2 space-y-2 text-sm text-zinc-300">
              {blocked.map((answer) => (
                <li key={answer.id}>
                  <div className="font-medium">{answer.question}</div>
                  <div className="text-zinc-500">
                    {answer.clarification || "Waiting on a personal judgment."}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {analysis && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Fit
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-zinc-300">
              {analysis.verdict}
            </p>
            {analysis.gaps.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-sm text-zinc-400">
                {analysis.gaps.map((gap) => (
                  <li key={gap} className="border-l-2 border-rose-900 pl-2">
                    {gap}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {job.notes && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Notes
            </h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">
              {job.notes}
            </p>
          </section>
        )}

        {job.cover_letter.trim() && (
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Cover letter
            </h3>
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-zinc-800 bg-zinc-900/40 p-3 text-sm leading-relaxed text-zinc-300">
              {job.cover_letter}
            </pre>
          </section>
        )}

        <JobPeople
          jobId={job.id}
          company={job.company}
          role={job.role}
          onChanged={onPeopleChanged}
        />

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            Job description
          </h3>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-sm leading-relaxed text-zinc-400">
            {job.jd_text || "No JD captured yet."}
          </pre>
        </section>
      </div>
    </div>
  );
}
