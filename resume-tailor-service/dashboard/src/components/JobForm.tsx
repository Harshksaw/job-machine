import { useState } from "react";
import { Save, X } from "lucide-react";
import type { JobWorkspaceInput } from "../types";
import {
  emptyJobInput,
  JOB_PRIORITIES,
  JOB_STATUSES,
  JOB_STATUS_LABEL,
} from "../lib/jobs";

interface Props {
  onCancel: () => void;
  onSave: (body: JobWorkspaceInput) => Promise<void>;
}

const field =
  "mt-1 w-full rounded-md border border-zinc-700 bg-zinc-900 px-2.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500/40";

export default function JobForm({ onCancel, onSave }: Props) {
  const [form, setForm] = useState<JobWorkspaceInput>(emptyJobInput);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = <K extends keyof JobWorkspaceInput>(
    key: K,
    value: JobWorkspaceInput[K]
  ) => setForm((current) => ({ ...current, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.company.trim() || !form.role.trim()) {
      setError("Company and role are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await onSave(form);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create dossier.");
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/75 p-3"
      onClick={onCancel}
    >
      <form
        className="flex max-h-[94vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-label="New job dossier"
      >
        <header className="flex items-center border-b border-zinc-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-100">New job dossier</h2>
          <button
            type="button"
            onClick={onCancel}
            className="ml-auto rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="grid gap-4 overflow-y-auto p-4 sm:grid-cols-2">
          <label className="text-xs font-medium text-zinc-400">
            Company
            <input
              autoFocus
              className={field}
              value={form.company}
              onChange={(event) => set("company", event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Role
            <input
              className={field}
              value={form.role}
              onChange={(event) => set("role", event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Job URL
            <input
              className={field}
              type="url"
              value={form.job_url}
              onChange={(event) => set("job_url", event.target.value)}
              placeholder="https://"
            />
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Source
            <input
              className={field}
              list="job-source-options"
              value={form.source}
              onChange={(event) => set("source", event.target.value)}
              placeholder="LinkedIn"
            />
            <datalist id="job-source-options">
              <option value="LinkedIn" />
              <option value="Wellfound" />
              <option value="Company site" />
              <option value="Referral" />
              <option value="Recruiter" />
            </datalist>
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Location
            <input
              className={field}
              value={form.location}
              onChange={(event) => set("location", event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Work mode
            <input
              className={field}
              value={form.work_mode}
              onChange={(event) => set("work_mode", event.target.value)}
              placeholder="Remote, hybrid, onsite"
            />
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Status
            <select
              className={field}
              value={form.status}
              onChange={(event) => set("status", event.target.value)}
            >
              {JOB_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {JOB_STATUS_LABEL[status]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-zinc-400">
            Priority
            <select
              className={field}
              value={form.priority}
              onChange={(event) => set("priority", event.target.value)}
            >
              {JOB_PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {priority[0].toUpperCase() + priority.slice(1)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-zinc-400 sm:col-span-2">
            Job description
            <textarea
              className={`${field} min-h-56 resize-y font-mono text-xs leading-relaxed`}
              value={form.jd_text}
              onChange={(event) => set("jd_text", event.target.value)}
            />
          </label>
          {error && (
            <p className="text-sm text-rose-400 sm:col-span-2" role="alert">
              {error}
            </p>
          )}
        </div>

        <footer className="flex justify-end gap-2 border-t border-zinc-800 px-4 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saving ? "Creating..." : "Create"}
          </button>
        </footer>
      </form>
    </div>
  );
}
