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
import type {
  ApplicationAnswer,
  ApplicationAnswerInput,
  JobDecision,
  JobSummary,
  JobWorkspace,
} from "../types";
import {
  addJobActivity,
  decideJob,
  getJob,
  listJobs,
  updateApplicationAnswer,
} from "../api";
import JobPeople from "./JobPeople";
import {
  countByStatus,
  fitTone,
  formatJobDate,
  inboxBlocker,
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
  const [queue, setQueue] = useState<InboxQueue>("needs-you");
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
    if (hash === "inbox/personal-answers") {
      setSelectedId("personal-answers");
      return;
    }
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
    if (selectedId === "personal-answers") {
      setTicket(null);
      setTicketLoading(false);
      return;
    }
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
    <div className="flex min-h-[calc(100vh-6rem)] flex-col overflow-hidden rounded-lg border border-zinc-700 bg-canvas">
      <div
        className="grid grid-cols-2 gap-px border-b border-zinc-700 bg-zinc-800 sm:grid-cols-4 lg:grid-cols-7"
        role="group"
        aria-label="Pipeline counts"
      >
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
            aria-label={`${JOB_STATUS_LABEL[status]}: ${counts[status] ?? 0}`}
            className="bg-canvas px-3 py-3 text-left hover:bg-raised"
          >
            <div className="text-xs font-medium text-zinc-400">
              {JOB_STATUS_LABEL[status]}
            </div>
            <div className="mt-0.5 text-xl font-semibold tabular-nums text-zinc-100">
              {counts[status] ?? 0}
            </div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-700 bg-surface px-3 py-3 sm:px-4">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <label htmlFor="inbox-search" className="visually-hidden">
            Search tickets
          </label>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" aria-hidden />
          <input
            id="inbox-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search company or role"
            className="jm-input pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Inbox queues">
          {INBOX_QUEUES.map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setQueue(key)}
              aria-pressed={queue === key}
              className={`rounded-md px-3 py-2 text-sm font-medium ${
                queue === key
                  ? "bg-teal-600 text-white"
                  : "border border-zinc-600 text-zinc-200 hover:bg-raised"
              }`}
            >
              {INBOX_QUEUE_LABEL[key]}
              <span className="ml-1.5 tabular-nums opacity-80">
                {queueCounts[key]}
              </span>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setMinFit(minFit === 8 ? null : 8)}
          aria-pressed={minFit === 8}
          className={`rounded-md px-3 py-2 text-sm font-medium ${
            minFit === 8
              ? "bg-emerald-700 text-white"
              : "border border-zinc-600 text-zinc-200 hover:bg-raised"
          }`}
        >
          Fit 8+
        </button>
        <span className="ml-auto text-sm text-zinc-400">
          {shown.length} tickets
        </span>
        <button
          type="button"
          onClick={() => void loadList()}
          className="rounded-md p-2 text-zinc-300 hover:bg-raised hover:text-zinc-100"
          aria-label="Refresh inbox"
        >
          <RefreshCw className="h-4 w-4" aria-hidden />
        </button>
      </div>

      {(error || notice) && (
        <div
          role="status"
          className={`flex items-center gap-2 border-b px-4 py-2.5 text-sm ${
            error
              ? "border-rose-800 bg-rose-950/30 text-rose-200"
              : "border-teal-800 bg-teal-950/30 text-teal-100"
          }`}
        >
          {error && <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />}
          {error || notice}
        </div>
      )}

      {phase === "loading" ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-zinc-300">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Loading tickets...
        </div>
      ) : phase === "error" ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-zinc-200">
          <AlertTriangle className="h-6 w-6 text-rose-300" aria-hidden />
          {error}
          <button
            type="button"
            onClick={() => void loadList()}
            className="jm-btn-secondary"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(12rem,38vh)_minmax(0,1fr)] lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] lg:grid-rows-1">
          <aside className="min-h-0 overflow-y-auto border-b border-zinc-700 bg-surface lg:border-b-0 lg:border-r">
            <h2 className="visually-hidden">Tickets</h2>
            {(queue === "needs-you" || queue === "all") && (
              <PersonalAnswersRow
                selected={selectedId === "personal-answers"}
                onSelect={() => setSelectedId("personal-answers")}
              />
            )}
            {shown.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-6 py-16 text-center text-sm text-zinc-400">
                <InboxIcon className="h-8 w-8" aria-hidden />
                No tickets in this queue.
              </div>
            ) : (
              <ul className="divide-y divide-zinc-800">
                {shown.map((job) => (
                  <li key={job.id}>
                    <TicketRow
                      job={job}
                      selected={job.id === selectedId}
                      onSelect={() => setSelectedId(job.id)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </aside>

          <section className="min-h-0 overflow-y-auto bg-canvas" aria-live="polite">
            {selectedId === "personal-answers" ? (
              <PersonalAnswersDetail />
            ) : ticketLoading ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-zinc-300">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Opening ticket...
              </div>
            ) : ticket ? (
              <TicketDetail
                job={ticket}
                busy={busy}
                onDecide={(decision) => void decide(decision)}
                onUpdated={(job) => {
                  setTicket(job);
                  void loadList(true);
                }}
                onOpenDossier={() => onOpenDossier(ticket.id)}
                onPeopleChanged={peopleChanged}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-zinc-400">
                <InboxIcon className="h-8 w-8" aria-hidden />
                Pick a ticket. Save an answer, approve outreach, or hold it.
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
    JOB_STATUS_STYLE[job.status] ?? "border-zinc-600 bg-zinc-800 text-zinc-300";
  const blocker = inboxBlocker(job);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      aria-label={`${job.company}, ${job.role}${job.needs_user_input ? ", needs you" : ""}`}
      className={`w-full px-4 py-3.5 text-left transition ${
        selected
          ? "bg-teal-950/40 shadow-[inset_3px_0_0_#2dd4bf]"
          : "hover:bg-raised"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold text-zinc-100">
            {job.company}
          </div>
          <div className="mt-0.5 truncate text-sm text-zinc-300">{job.role}</div>
        </div>
        <span
          className={`jm-badge shrink-0 ${fitTone(job.fit_score)}`}
        >
          Fit {job.fit_score ?? "—"}
        </span>
      </div>
      {blocker && (
        <p className="mt-2 line-clamp-2 text-sm leading-snug text-zinc-200">
          {blocker}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className={`jm-badge ${statusClass}`}>
          {JOB_STATUS_LABEL[job.status] ?? job.status}
        </span>
        {job.needs_user_input && (
          <span className="jm-badge border-amber-500 bg-amber-950/50 text-amber-100">
            Needs you
          </span>
        )}
        {job.queued_person_count > 0 ? (
          <span className="jm-badge border-sky-600 bg-sky-950/40 text-sky-100">
            <Send className="h-3 w-3" aria-hidden />
            {job.queued_person_count} to approve
          </span>
        ) : job.person_count > 0 ? (
          <span className="jm-badge border-zinc-600 text-zinc-200">
            <Users className="h-3 w-3" aria-hidden />
            {job.person_count} {job.person_count === 1 ? "person" : "people"}
          </span>
        ) : (job.fit_score ?? 0) >= 8 ? (
          <span className="jm-badge border-amber-600 text-amber-100">
            Add people
          </span>
        ) : null}
        {job.has_cover_letter && (
          <span className="jm-badge border-teal-700 text-teal-100">
            <FileText className="h-3 w-3" aria-hidden />
            Kit ready
          </span>
        )}
        {job.source && (
          <span className="truncate text-xs text-zinc-400">{job.source}</span>
        )}
        <time className="ml-auto text-xs text-zinc-400">
          {formatJobDate(job.updated_at)}
        </time>
      </div>
    </button>
  );
}

const PERSONAL_BLANKS = [
  {
    title: "Salary when a number is required and no band is posted",
    hint: "CAD, USD, or a rule such as skip that listing.",
  },
  {
    title: "Notice period / earliest start date",
    hint: "Suggested default is after graduation. Confirm or replace.",
  },
  {
    title: "Canadian work status, exact wording",
    hint: "Citizen / PR / study permit / PGWP / other.",
  },
  {
    title: "French level",
    hint: "None / beginner / intermediate / professional / fluent.",
  },
  {
    title: "Willing to start immediately?",
    hint: "Hard yes or no for forms that require it.",
  },
  {
    title: "Date of birth",
    hint: "Or write that listings requiring DOB should be skipped.",
  },
  {
    title: "LinkedIn invite budget reset",
    hint: "Do not send until you say yes. Max 12 per session.",
  },
];

function PersonalAnswersRow({
  selected,
  onSelect,
}: {
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`w-full border-b border-amber-800 px-4 py-3.5 text-left transition ${
        selected
          ? "bg-amber-950/40 shadow-[inset_3px_0_0_#fbbf24]"
          : "bg-amber-950/15 hover:bg-amber-950/30"
      }`}
    >
      <div className="text-base font-semibold text-amber-100">Fill personal answers</div>
      <div className="mt-1 text-sm text-amber-100/80">
        7 blanks in docs/PERSONAL-ANSWERS.md. Values stay local.
      </div>
    </button>
  );
}

function PersonalAnswersDetail() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-zinc-700 px-5 py-5 sm:px-8">
        <h2 className="text-2xl font-semibold text-zinc-100">Personal answers</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-zinc-300">
          Edit the gitignored file. Do not paste street, salary, DOB, or status
          wording into chat or any committed file.
        </p>
      </header>
      <div className="space-y-4 px-5 py-6 sm:px-8">
        <p className="rounded-md border border-zinc-600 bg-raised px-3 py-2 font-mono text-sm text-zinc-300">
          docs/PERSONAL-ANSWERS.md
        </p>
        <ul className="space-y-3">
          {PERSONAL_BLANKS.map((item) => (
            <li
              key={item.title}
              className="rounded-md border border-amber-700 bg-amber-950/20 p-4"
            >
              <div className="text-base font-medium text-zinc-100">{item.title}</div>
              <div className="mt-1 text-sm text-zinc-300">{item.hint}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function toAnswerInput(answer: ApplicationAnswer): ApplicationAnswerInput {
  return {
    question: answer.question,
    answer: answer.answer,
    constraints: answer.constraints,
    status: answer.status,
    source_ids: answer.source_ids,
    needs_user_input: answer.needs_user_input,
    clarification: answer.clarification,
  };
}

function BlockedAnswerEditor({
  jobId,
  answer,
  onUpdated,
}: {
  jobId: string;
  answer: ApplicationAnswer;
  onUpdated: (job: JobWorkspace) => void;
}) {
  const [text, setText] = useState(answer.answer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setText(answer.answer), [answer.answer]);

  const save = async (status: "approved" | "draft") => {
    setBusy(true);
    setError("");
    try {
      const filled = text.trim();
      onUpdated(
        await updateApplicationAnswer(
          jobId,
          answer.id,
          {
            ...toAnswerInput(answer),
            answer: text,
            needs_user_input: status !== "approved" || !filled,
            status,
            clarification: status === "approved" ? "" : answer.clarification,
          },
          "Inbox"
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save answer.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="border-t border-amber-800/60 pt-4 first:border-t-0 first:pt-0">
      <label htmlFor={`answer-${answer.id}`} className="block text-base font-medium text-zinc-100">
        {answer.question}
      </label>
      <p className="mt-1 text-sm text-zinc-300">
        {answer.clarification || "Waiting on a personal judgment."}
      </p>
      <textarea
        id={`answer-${answer.id}`}
        value={text}
        onChange={(event) => setText(event.target.value)}
        rows={4}
        placeholder="Type the answer here. Leave blank if you want this listing skipped."
        className="jm-input mt-3 min-h-[6rem] resize-y leading-relaxed"
      />
      {error && <p className="mt-2 text-sm text-rose-300">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void save("approved")}
          disabled={busy || !text.trim()}
          className="jm-btn-primary"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Check className="h-4 w-4" aria-hidden />}
          Save answer
        </button>
        <button
          type="button"
          onClick={() => void save("draft")}
          disabled={busy}
          className="jm-btn-secondary"
        >
          Keep as draft
        </button>
      </div>
    </li>
  );
}

function TicketDetail({
  job,
  busy,
  onDecide,
  onUpdated,
  onOpenDossier,
  onPeopleChanged,
}: {
  job: JobWorkspace;
  busy: JobDecision | null;
  onDecide: (decision: JobDecision) => void;
  onUpdated: (job: JobWorkspace) => void;
  onOpenDossier: () => void;
  onPeopleChanged: () => void;
}) {
  const listing = safeHref(job.job_url);
  const analysis = job.fit_analysis;
  const blocked = job.application_answers.filter((answer) => answer.needs_user_input);
  const kitReview = job.application_answers.find(
    (answer) =>
      answer.needs_user_input &&
      answer.question.toLowerCase().includes("cover letter")
  );
  const canApprove = job.status === "discovered" || job.status === "researching";
  const canHold =
    canApprove || job.status === "ready" || job.status === "applying";
  const canMarkApplied = job.status === "ready" || job.status === "applying";
  const [kitBusy, setKitBusy] = useState(false);

  const markKitReviewed = async () => {
    setKitBusy(true);
    try {
      if (kitReview) {
        onUpdated(
          await updateApplicationAnswer(
            job.id,
            kitReview.id,
            {
              ...toAnswerInput(kitReview),
              answer: "Kit reviewed in Inbox. Do not resend the application.",
              needs_user_input: false,
              status: "approved",
              clarification: "",
            },
            "Inbox"
          )
        );
      } else {
        onUpdated(
          await addJobActivity(job.id, {
            kind: "decision",
            title: "Kit reviewed",
            detail: "Cover letter marked reviewed in Inbox. Do not resend.",
            session: "Inbox",
            occurred_at: null,
            external_id: null,
          })
        );
      }
    } finally {
      setKitBusy(false);
    }
  };

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-zinc-700 px-5 py-5 sm:px-8">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-2xl font-semibold leading-tight text-zinc-100">{job.company}</h2>
            <p className="mt-1 text-lg text-zinc-200">{job.role}</p>
            <p className="mt-2 text-sm text-zinc-400">
              {[job.location, job.work_mode, job.source, job.compensation]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </div>
          <span className={`jm-badge px-2.5 py-1 text-sm ${fitTone(job.fit_score)}`}>
            {job.fit_score == null ? "Fit —" : `Fit ${job.fit_score}/10`}
          </span>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {canApprove && (
            <button
              type="button"
              onClick={() => onDecide("approve")}
              disabled={busy !== null}
              className="jm-btn-primary"
            >
              {busy === "approve" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Check className="h-4 w-4" aria-hidden />
              )}
              Approve to apply
            </button>
          )}
          {canHold && (
            <button
              type="button"
              onClick={() => onDecide("hold")}
              disabled={busy !== null}
              className="jm-btn-secondary"
            >
              {busy === "hold" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Pause className="h-4 w-4" aria-hidden />
              )}
              Hold
            </button>
          )}
          {canMarkApplied && (
            <button
              type="button"
              onClick={() => onDecide("applied")}
              disabled={busy !== null}
              className="jm-btn-secondary"
            >
              {busy === "applied" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Send className="h-4 w-4" aria-hidden />
              )}
              Mark applied
            </button>
          )}
          {listing && (
            <a
              href={listing}
              target="_blank"
              rel="noopener noreferrer"
              className="jm-btn-secondary"
            >
              <ExternalLink className="h-4 w-4" aria-hidden />
              Open listing
            </a>
          )}
          <button
            type="button"
            onClick={onOpenDossier}
            className="jm-btn-secondary"
          >
            Full dossier
          </button>
        </div>
      </header>

      <div className="space-y-8 px-5 py-6 sm:px-8 lg:px-10">
        {job.next_action && (
          <p className="flex items-start gap-2 text-base leading-relaxed text-amber-100">
            <Clock3 className="mt-1 h-5 w-5 shrink-0" aria-hidden />
            {job.next_action}
          </p>
        )}

        {blocked.length > 0 && (
          <section className="rounded-md border border-amber-700 bg-amber-950/20 p-4">
            <h3 className="text-sm font-semibold text-amber-100">
              Needs your input
            </h3>
            <ul className="mt-3 space-y-4">
              {blocked.map((answer) => (
                <BlockedAnswerEditor
                  key={answer.id}
                  jobId={job.id}
                  answer={answer}
                  onUpdated={onUpdated}
                />
              ))}
            </ul>
          </section>
        )}

        {analysis && (
          <section>
            <h3 className="jm-section-title">Fit</h3>
            <p className="mt-2 text-base leading-7 text-zinc-200">
              {analysis.verdict}
            </p>
            {analysis.gaps.length > 0 && (
              <ul className="mt-3 space-y-2 text-sm leading-relaxed text-zinc-300">
                {analysis.gaps.map((gap) => (
                  <li key={gap} className="border-l-2 border-rose-500 pl-3">
                    {gap}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {job.notes && (
          <section>
            <h3 className="jm-section-title">Notes</h3>
            <p className="mt-2 whitespace-pre-wrap text-base leading-7 text-zinc-200">
              {job.notes}
            </p>
          </section>
        )}

        {job.cover_letter.trim() && (
          <section>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="jm-section-title">Cover letter</h3>
              <button
                type="button"
                onClick={() => void markKitReviewed()}
                disabled={kitBusy}
                className="jm-btn-primary ml-auto"
              >
                {kitBusy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="h-4 w-4" aria-hidden />
                )}
                Kit looks good
              </button>
            </div>
            <article className="mt-3 whitespace-pre-wrap text-base leading-7 text-zinc-100">
              {job.cover_letter}
            </article>
          </section>
        )}

        <JobPeople
          jobId={job.id}
          company={job.company}
          role={job.role}
          onChanged={onPeopleChanged}
        />

        <section>
          <h3 className="jm-section-title">Job description</h3>
          <pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-7 text-zinc-300">
            {job.jd_text || "No JD captured yet."}
          </pre>
        </section>
      </div>
    </div>
  );
}
