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
  discovered: "border-zinc-500 bg-zinc-800 text-zinc-100",
  researching: "border-cyan-400 bg-cyan-950 text-cyan-100",
  ready: "border-teal-400 bg-teal-950 text-teal-100",
  applying: "border-amber-400 bg-amber-950 text-amber-100",
  applied: "border-sky-400 bg-sky-950 text-sky-100",
  outreach: "border-fuchsia-400 bg-fuchsia-950 text-fuchsia-100",
  interview: "border-emerald-400 bg-emerald-950 text-emerald-100",
  offer: "border-lime-400 bg-lime-950 text-lime-100",
  rejected: "border-rose-400 bg-rose-950 text-rose-100",
  skipped: "border-zinc-500 bg-zinc-800 text-zinc-200",
  archived: "border-zinc-500 bg-zinc-800 text-zinc-300",
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
    research_brief: "",
    apply_url: "",
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
    research_brief: job.research_brief ?? "",
    apply_url: job.apply_url ?? "",
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
  if (score == null) return "border-zinc-400 bg-zinc-800 text-zinc-100";
  if (score >= 8) return "border-emerald-300 bg-emerald-950 text-emerald-100";
  if (score >= 6) return "border-amber-300 bg-amber-950 text-amber-100";
  return "border-rose-300 bg-rose-950 text-rose-100";
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
  "follow-up",
  "needs-you",
  "all",
] as const;

export type InboxQueue = (typeof INBOX_QUEUES)[number];

export const INBOX_QUEUE_LABEL: Record<InboxQueue, string> = {
  decide: "Needs decision",
  ready: "Approved",
  applied: "Applied",
  "follow-up": "Follow up",
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
    follow_up_eligible?: boolean;
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
  if (queue === "follow-up") return Boolean(job.follow_up_eligible);
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
