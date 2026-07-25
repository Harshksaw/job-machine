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
  skipped: "border-zinc-700 bg-zinc-900 text-zinc-500",
  archived: "border-zinc-700 bg-zinc-900 text-zinc-500",
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
  if (score == null) return "border-zinc-700 bg-zinc-900 text-zinc-500";
  if (score >= 8) return "border-emerald-700/70 bg-emerald-950/50 text-emerald-300";
  if (score >= 6) return "border-amber-700/70 bg-amber-950/50 text-amber-300";
  return "border-rose-800/70 bg-rose-950/40 text-rose-300";
}
