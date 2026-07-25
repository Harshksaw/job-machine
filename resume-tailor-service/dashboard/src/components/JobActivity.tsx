import { useMemo, useState } from "react";
import {
  Clock3,
  Download,
  History,
  Loader2,
  Plus,
  RotateCcw,
} from "lucide-react";
import type { JobWorkspace } from "../types";
import { addJobActivity, restoreJobRevision } from "../api";
import { formatJobDate } from "../lib/jobs";

interface Props {
  job: JobWorkspace;
  onUpdated: (job: JobWorkspace) => void;
}

const field =
  "w-full rounded-md border border-zinc-700 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500/30";

export default function JobActivity({ job, onUpdated }: Props) {
  const [kind, setKind] = useState("note");
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [session, setSession] = useState("Manual");
  const [occurredAt, setOccurredAt] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const activities = useMemo(
    () =>
      [...job.activities].sort((a, b) =>
        (b.occurred_at || b.created_at).localeCompare(a.occurred_at || a.created_at)
      ),
    [job.activities]
  );
  const revisions = useMemo(
    () => [...job.revisions].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [job.revisions]
  );

  const add = async () => {
    if (!title.trim()) return;
    setBusy("activity");
    setError("");
    try {
      const updated = await addJobActivity(job.id, {
        kind,
        title,
        detail,
        session,
        occurred_at: occurredAt ? new Date(occurredAt).toISOString() : null,
        external_id: null,
      });
      setTitle("");
      setDetail("");
      setOccurredAt("");
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add activity.");
    } finally {
      setBusy("");
    }
  };

  const restore = async (revisionId: string) => {
    if (!window.confirm("Restore this complete dossier revision?")) return;
    setBusy(revisionId);
    setError("");
    try {
      onUpdated(await restoreJobRevision(job.id, revisionId, "Manual restore"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore revision.");
    } finally {
      setBusy("");
    }
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(job, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${job.company}-${job.role}-dossier.json`
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="grid divide-y divide-zinc-800 xl:grid-cols-2 xl:divide-x xl:divide-y-0">
      <section className="px-4 py-5 lg:px-6">
        <div className="flex items-center gap-2">
          <Clock3 className="h-4 w-4 text-zinc-500" />
          <h3 className="text-sm font-semibold text-zinc-200">Activity ledger</h3>
          <button
            type="button"
            onClick={exportJson}
            className="ml-auto rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="Export dossier JSON"
            title="Export dossier"
          >
            <Download className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-zinc-500">
            Type
            <select
              className={`${field} mt-1`}
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              <option value="note">Note</option>
              <option value="research">Research</option>
              <option value="applied">Applied</option>
              <option value="outreach">Outreach</option>
              <option value="reply">Reply</option>
              <option value="interview">Interview</option>
              <option value="decision">Decision</option>
            </select>
          </label>
          <label className="text-xs font-medium text-zinc-500">
            Session
            <input
              className={`${field} mt-1`}
              value={session}
              onChange={(event) => setSession(event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-500 sm:col-span-2">
            Event
            <input
              className={`${field} mt-1`}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-500 sm:col-span-2">
            Detail
            <textarea
              className={`${field} mt-1 min-h-24 resize-y`}
              value={detail}
              onChange={(event) => setDetail(event.target.value)}
            />
          </label>
          <label className="text-xs font-medium text-zinc-500">
            Occurred at
            <input
              className={`${field} mt-1`}
              type="datetime-local"
              value={occurredAt}
              onChange={(event) => setOccurredAt(event.target.value)}
            />
          </label>
          <div className="flex items-end justify-end">
            <button
              type="button"
              onClick={() => void add()}
              disabled={!title.trim() || busy === "activity"}
              className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-2 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-40"
            >
              {busy === "activity" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              Add event
            </button>
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}

        <div className="mt-6 divide-y divide-zinc-800 border-y border-zinc-800">
          {activities.map((activity) => (
            <article key={activity.id} className="py-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md border border-zinc-700 px-1.5 py-0.5 text-[11px] uppercase text-zinc-500">
                  {activity.kind}
                </span>
                <h4 className="text-sm font-medium text-zinc-200">{activity.title}</h4>
                <time className="ml-auto text-xs text-zinc-600">
                  {formatJobDate(activity.occurred_at || activity.created_at)}
                </time>
              </div>
              {activity.session && (
                <div className="mt-1 text-xs text-cyan-700">{activity.session}</div>
              )}
              {activity.detail && (
                <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">
                  {activity.detail}
                </p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="px-4 py-5 lg:px-6">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-zinc-500" />
          <h3 className="text-sm font-semibold text-zinc-200">Restorable history</h3>
          <span className="ml-auto text-xs text-zinc-600">{revisions.length}</span>
        </div>
        <div className="mt-4 divide-y divide-zinc-800 border-y border-zinc-800">
          {revisions.map((revision) => (
            <article key={revision.id} className="py-4">
              <div className="flex items-start gap-2">
                <div className="min-w-0">
                  <h4 className="text-sm font-medium text-zinc-200">
                    {revision.reason}
                  </h4>
                  <p className="mt-1 text-xs text-zinc-600">
                    {formatJobDate(revision.created_at)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void restore(revision.id)}
                  disabled={busy === revision.id}
                  className="ml-auto rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-teal-300 disabled:opacity-40"
                  aria-label={`Restore ${revision.reason}`}
                  title="Restore revision"
                >
                  {busy === revision.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RotateCcw className="h-4 w-4" />
                  )}
                </button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {revision.changed_fields.map((fieldName) => (
                  <span
                    key={fieldName}
                    className="rounded-md border border-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-600"
                  >
                    {fieldName.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-zinc-600 hover:text-zinc-400">
                  Snapshot
                </summary>
                <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-zinc-800 bg-black/30 p-3 text-[11px] leading-relaxed text-zinc-500">
                  {JSON.stringify(revision.snapshot, null, 2)}
                </pre>
              </details>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
