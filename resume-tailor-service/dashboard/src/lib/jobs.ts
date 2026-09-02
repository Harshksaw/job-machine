import type { JobWorkspace, JobWorkspaceInput } from "../types";

export const JOB_STATUSES = [
  "discovered",
  "researching",
  "ready",
  "applying",
  "applied",
  "outreach",
  "interview",
  "offer",
  "rejected",
  "skipped",
  "archived",
] as const;

export const JOB_STATUS_LABEL: Record<string, string> = {
  discovered: "Discovered",
  researching: "Researching",
  ready: "Ready",
  applying: "Applying",
  applied: "Applied",
  outreach: "Outreach",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  skipped: "Skipped",
  archived: "Archived",
};

export const JOB_STATUS_STYLE: Record<string, string> = {
  discovered: "border-zinc-600 bg-zinc-800 text-zinc-300",
  researching: "border-cyan-700/70 bg-cyan-950/50 text-cyan-300",
  ready: "border-teal-700/70 bg-teal-950/50 text-teal-300",
  applying: "border-amber-700/70 bg-amber-950/50 text-amber-300",
  applied: "border-sky-700/70 bg-sky-950/50 text-sky-300",
  outreach: "border-fuchsia-800/70 bg-fuchsia-950/40 text-fuchsia-300",
  interview: "border-emerald-700/70 bg-emerald-950/50 text-emerald-300",
  offer: "border-lime-700/70 bg-lime-950/50 text-lime-300",
  rejected: "border-rose-800/70 bg-rose-950/40 text-rose-300",
  skipped: "border-zinc-600 bg-zinc-800 text-zinc-300",
  archived: "border-zinc-600 bg-zinc-800 text-zinc-300",
};

export const JOB_PRIORITIES = ["low", "normal", "high", "dream"] as const;

export function emptyJobInput(): JobWorkspaceInput {
  return {
    company: "",
    role: "",
    job_url: "",
    source: "",
    location: "",
    work_mode: "",
    compensation: "",
    status: "discovered",
    priority: "normal",
    fit_score: null,
    jd_text: "",
    company_context: "",
    why_this_role: "",
    notes: "",
    next_action: "",
    deadline: "",
    fit_analysis: null,
    cover_letter: "",
    application_answers: [],
    tailored_resume_id: null,
  };
}

export function toJobInput(job: JobWorkspace): JobWorkspaceInput {
  return {
    company: job.company,
    role: job.role,
    job_url: job.job_url,
    source: job.source,
    location: job.location,
    work_mode: job.work_mode,
    compensation: job.compensation,
    status: job.status,
    priority: job.priority,
    fit_score: job.fit_score,
    jd_text: job.jd_text,
    company_context: job.company_context,
    why_this_role: job.why_this_role,
    notes: job.notes,
    next_action: job.next_action,
    deadline: job.deadline,
    fit_analysis: job.fit_analysis,
    cover_letter: job.cover_letter,
    application_answers: job.application_answers,
    tailored_resume_id: job.tailored_resume_id,
  };
}

export function formatJobDate(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-CA", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function fitTone(score: number | null): string {
  if (score == null) return "border-zinc-600 bg-zinc-800 text-zinc-300";
  if (score >= 8) return "border-emerald-600 bg-emerald-950/50 text-emerald-200";
  if (score >= 6) return "border-amber-600 bg-amber-950/50 text-amber-200";
  return "border-rose-700 bg-rose-950/40 text-rose-200";
}

export function inboxBlocker(job: {
  needs_user_input?: boolean;
  queued_person_count?: number;
  next_action?: string;
  notes?: string;
}): string {
  if (job.needs_user_input) {
    const action = (job.next_action ?? "").trim();
    return action || "Needs your input";
  }
  const queued = job.queued_person_count ?? 0;
  if (queued > 0) {
    return queued === 1
      ? "1 outreach waiting approval"
      : `${queued} outreach waiting approval`;
  }
  const action = (job.next_action ?? "").trim();
  if (action) return action;
  return ((job.notes ?? "").trim().split("\n")[0] ?? "").trim();
}

export const INBOX_QUEUES = [
  "decide",
  "ready",
  "applied",
  "needs-you",
  "all",
] as const;

export type InboxQueue = (typeof INBOX_QUEUES)[number];

export const INBOX_QUEUE_LABEL: Record<InboxQueue, string> = {
  decide: "Needs decision",
  ready: "Approved",
  applied: "Applied",
  "needs-you": "Needs you",
  all: "All",
};

const CLOSED = new Set(["rejected", "skipped", "archived"]);
const DECIDE = new Set(["discovered", "researching"]);
const READY = new Set(["ready", "applying"]);
const APPLIED = new Set(["applied", "outreach", "interview", "offer"]);

export function inInboxQueue(
  job: {
    status: string;
    needs_user_input?: boolean;
    queued_person_count?: number;
  },
  queue: InboxQueue
): boolean {
  if (queue === "all") return !CLOSED.has(job.status);
  if (queue === "needs-you") {
    return (
      !CLOSED.has(job.status) &&
      (Boolean(job.needs_user_input) || (job.queued_person_count ?? 0) > 0)
    );
  }
  if (queue === "decide") return DECIDE.has(job.status);
  if (queue === "ready") return READY.has(job.status);
  return APPLIED.has(job.status);
}

export function sortInbox<
  T extends { fit_score: number | null; updated_at: string; priority: string },
>(jobs: T[]): T[] {
  const rank = (priority: string) =>
    priority === "dream" ? 0 : priority === "high" ? 1 : priority === "normal" ? 2 : 3;
  return [...jobs].sort((a, b) => {
    const fit = (b.fit_score ?? -1) - (a.fit_score ?? -1);
    if (fit !== 0) return fit;
    const pri = rank(a.priority) - rank(b.priority);
    if (pri !== 0) return pri;
    return b.updated_at.localeCompare(a.updated_at);
  });
}

export function countByStatus(jobs: { status: string }[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const status of JOB_STATUSES) counts[status] = 0;
  for (const job of jobs) {
    counts[job.status] = (counts[job.status] ?? 0) + 1;
  }
  return counts;
}
