import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ExternalLink,
  FileText,
  FormInput,
  Loader2,
  Mail,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import type { JobWorkspace, JobWorkspaceInput } from "../types";
import {
  deleteJob,
  generateJobKit,
  getJob,
  tailorJob,
  updateJob,
} from "../api";
import {
  fitTone,
  JOB_PRIORITIES,
  JOB_STATUSES,
  JOB_STATUS_LABEL,
  JOB_STATUS_STYLE,
  toJobInput,
} from "../lib/jobs";
import { safeHref } from "../lib/people";
import JobActivity from "./JobActivity";
import JobAnswers from "./JobAnswers";
import JobLetter from "./JobLetter";
import JobOverview from "./JobOverview";
import JobResume from "./JobResume";

type Tab = "overview" | "resume" | "letter" | "answers" | "activity";

interface Props {
  job: JobWorkspace;
  onUpdated: (job: JobWorkspace) => void;
  onDeleted: (jobId: string) => void;
  onDirtyChange: (dirty: boolean) => void;
  onPeopleChanged?: () => void;
}

const tabs: { id: Tab; label: string; icon: typeof FileText }[] = [
  { id: "overview", label: "Overview", icon: FormInput },
  { id: "resume", label: "Resume", icon: FileText },
  { id: "letter", label: "Letter", icon: Mail },
  { id: "answers", label: "Answers", icon: FormInput },
  { id: "activity", label: "Activity", icon: Activity },
];

export default function JobDetail({
  job,
  onUpdated,
  onDeleted,
  onDirtyChange,
  onPeopleChanged,
}: Props) {
  const [draft, setDraft] = useState<JobWorkspaceInput>(() => toJobInput(job));
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState<"save" | "kit" | "tailor" | "delete" | "tab" | null>(
    null
  );
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(toJobInput(job));
    setError("");
  }, [job.id, job.updated_at]);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(toJobInput(job)),
    [draft, job]
  );

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  const change = <K extends keyof JobWorkspaceInput>(
    key: K,
    value: JobWorkspaceInput[K]
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const persist = async (session = "Manual edit"): Promise<JobWorkspace> => {
    if (!dirty) return job;
    const updated = await updateJob(job.id, draft, session);
    onUpdated(updated);
    return updated;
  };

  const save = async () => {
    setBusy("save");
    setError("");
    try {
      await persist();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save dossier.");
    } finally {
      setBusy(null);
    }
  };

  const switchTab = async (next: Tab) => {
    if (next === tab) return;
    if (!dirty) {
      setTab(next);
      return;
    }
    setBusy("tab");
    setError("");
    try {
      await persist("Tab autosave");
      setTab(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save before changing tabs.");
    } finally {
      setBusy(null);
    }
  };

  const generate = async (returnTo: Tab = "overview") => {
    setBusy("kit");
    setError("");
    try {
      const saved = await persist("Pre-generation save");
      const updated = await generateJobKit(saved.id, "Application kit");
      onUpdated(updated);
      setTab(returnTo);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate kit.");
    } finally {
      setBusy(null);
    }
  };

  const tailor = async () => {
    setBusy("tailor");
    setError("");
    try {
      const saved = await persist("Pre-tailor save");
      await tailorJob(saved, "Resume tailoring");
      onUpdated(await getJob(saved.id));
      setTab("resume");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to tailor resume.");
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete the complete dossier for ${job.company}?`)) return;
    setBusy("delete");
    try {
      await deleteJob(job.id);
      onDeleted(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete dossier.");
      setBusy(null);
    }
  };

  const statusStyle =
    JOB_STATUS_STYLE[draft.status] ?? "border-zinc-700 bg-zinc-900 text-zinc-400";

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-zinc-950">
      <header className="border-b border-zinc-800 px-4 py-3 lg:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <div className="min-w-0 flex-1">
            <input
              className="w-full border-0 bg-transparent p-0 text-base font-semibold text-zinc-100 outline-none placeholder:text-zinc-700"
              value={draft.company}
              onChange={(event) => change("company", event.target.value)}
              aria-label="Company"
            />
            <input
              className="mt-0.5 w-full border-0 bg-transparent p-0 text-sm text-zinc-400 outline-none placeholder:text-zinc-700"
              value={draft.role}
              onChange={(event) => change("role", event.target.value)}
              aria-label="Role"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex h-8 items-center rounded-md border px-2 text-xs font-semibold ${fitTone(
                draft.fit_score
              )}`}
            >
              {draft.fit_score == null ? "Fit —" : `Fit ${draft.fit_score}/10`}
            </span>
            <select
              className={`h-8 rounded-md border px-2 text-xs font-medium outline-none ${statusStyle}`}
              value={draft.status}
              onChange={(event) => change("status", event.target.value)}
              aria-label="Job status"
            >
              {JOB_STATUSES.map((status) => (
                <option key={status} value={status} className="bg-zinc-900 text-zinc-200">
                  {JOB_STATUS_LABEL[status]}
                </option>
              ))}
            </select>
            <select
              className="h-8 rounded-md border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-300 outline-none"
              value={draft.priority}
              onChange={(event) => change("priority", event.target.value)}
              aria-label="Job priority"
            >
              {JOB_PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {priority === "dream"
                    ? "Dream target"
                    : `${priority[0].toUpperCase()}${priority.slice(1)} priority`}
                </option>
              ))}
            </select>
            {safeHref(draft.job_url) && (
              <a
                href={safeHref(draft.job_url)!}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md p-2 text-zinc-500 hover:bg-zinc-800 hover:text-cyan-300"
                aria-label="Open job listing"
                title="Open job listing"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
            <button
              type="button"
              onClick={() => void generate("overview")}
              disabled={busy !== null || draft.jd_text.trim().length < 80}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-teal-600 px-3 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-40"
            >
              {busy === "kit" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              Build kit
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={!dirty || busy !== null}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-zinc-700 px-3 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-30"
            >
              {busy === "save" || busy === "tab" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              {dirty ? "Save" : "Saved"}
            </button>
            <button
              type="button"
              onClick={() => void remove()}
              disabled={busy !== null}
              className="rounded-md p-2 text-zinc-600 hover:bg-zinc-800 hover:text-rose-300"
              aria-label="Delete dossier"
              title="Delete dossier"
            >
              {busy === "delete" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      </header>

      <nav className="flex shrink-0 overflow-x-auto border-b border-zinc-800 px-2">
        {tabs.map((item) => {
          const Icon = item.icon;
          const count =
            item.id === "answers"
              ? job.application_answers.length
              : item.id === "activity"
                ? job.activities.length
                : null;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => void switchTab(item.id)}
              disabled={busy === "tab"}
              className={`flex h-10 shrink-0 items-center gap-1.5 border-b-2 px-3 text-xs font-medium ${
                tab === item.id
                  ? "border-teal-400 text-teal-300"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {item.label}
              {count != null && (
                <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-500">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {error && (
        <div className="flex items-start gap-2 border-b border-rose-900/60 bg-rose-950/20 px-4 py-3 text-sm text-rose-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "overview" && (
          <JobOverview
            jobId={job.id}
            draft={draft}
            onChange={change}
            onPeopleChanged={onPeopleChanged}
          />
        )}
        {tab === "resume" && (
          <JobResume
            job={job}
            busy={busy === "tailor"}
            onTailor={tailor}
          />
        )}
        {tab === "letter" && (
          <JobLetter
            draft={draft}
            busy={busy === "kit"}
            onChange={(value) => change("cover_letter", value)}
            onGenerate={() => generate("letter")}
          />
        )}
        {tab === "answers" && (
          <JobAnswers job={job} onUpdated={onUpdated} />
        )}
        {tab === "activity" && (
          <JobActivity job={job} onUpdated={onUpdated} />
        )}
      </div>
    </div>
  );
}
