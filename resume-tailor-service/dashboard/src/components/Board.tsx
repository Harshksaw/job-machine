import { useMemo, useState } from "react";
import { FileText, Search, Send, Users } from "lucide-react";
import type { JobSummary } from "../types";
import { fitTone, formatJobDate, sortInbox } from "../lib/jobs";

const COLUMNS: { id: string; label: string; statuses: string[] }[] = [
  { id: "decide", label: "To decide", statuses: ["discovered", "researching"] },
  { id: "ready", label: "Approved", statuses: ["ready", "applying"] },
  { id: "applied", label: "Applied", statuses: ["applied"] },
  { id: "outreach", label: "Outreach", statuses: ["outreach"] },
  { id: "interview", label: "Interview / offer", statuses: ["interview", "offer"] },
];

interface Props {
  jobs: JobSummary[];
  onOpen: (jobId: string) => void;
}

export default function Board({ jobs, onOpen }: Props) {
  const [query, setQuery] = useState("");
  const [minFit, setMinFit] = useState<number | null>(null);

  const columns = useMemo(() => {
    const q = query.trim().toLowerCase();
    const visible = jobs.filter((job) => {
      if (minFit != null && (job.fit_score ?? 0) < minFit) return false;
      if (!q) return true;
      return (
        job.company.toLowerCase().includes(q) ||
        job.role.toLowerCase().includes(q) ||
        job.source.toLowerCase().includes(q) ||
        job.location.toLowerCase().includes(q)
      );
    });
    return COLUMNS.map((column) => ({
      ...column,
      jobs: sortInbox(visible.filter((job) => column.statuses.includes(job.status))),
    }));
  }, [jobs, query, minFit]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <label htmlFor="board-search" className="visually-hidden">
            Search board
          </label>
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
            aria-hidden
          />
          <input
            id="board-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search company, role, source"
            className="jm-input pl-9"
          />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-zinc-800 bg-surface p-1">
          {[null, 6, 8].map((value) => (
            <button
              key={value ?? "any"}
              type="button"
              onClick={() => setMinFit(value)}
              aria-pressed={minFit === value}
              className="jm-tab"
            >
              {value == null ? "Any fit" : `Fit ${value}+`}
            </button>
          ))}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 auto-cols-[minmax(13.5rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
        {columns.map((column) => (
          <section
            key={column.id}
            aria-label={column.label}
            className="flex min-h-0 flex-col rounded-xl border border-zinc-800 bg-surface"
          >
            <header className="flex items-center justify-between px-3 py-2.5">
              <h2 className="text-sm font-semibold text-zinc-200">{column.label}</h2>
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs tabular-nums text-zinc-400">
                {column.jobs.length}
              </span>
            </header>
            <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pb-2">
              {column.jobs.length === 0 ? (
                <li className="px-2 py-8 text-center text-sm text-zinc-600">Empty</li>
              ) : (
                column.jobs.map((job) => (
                  <li key={job.id}>
                    <BoardCard job={job} onOpen={() => onOpen(job.id)} />
                  </li>
                ))
              )}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function BoardCard({ job, onOpen }: { job: JobSummary; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-lg border border-zinc-800 bg-zinc-950/60 p-3 text-left transition-colors hover:border-zinc-700 hover:bg-zinc-900"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-zinc-100">{job.company}</div>
          <div className="mt-0.5 line-clamp-2 text-sm text-zinc-400">{job.role}</div>
        </div>
        <span className={`jm-badge shrink-0 ${fitTone(job.fit_score)}`}>
          {job.fit_score ?? "–"}
        </span>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
        {job.has_cover_letter && (
          <span className="inline-flex items-center gap-1 text-teal-300">
            <FileText className="h-3 w-3" aria-hidden />
            Kit
          </span>
        )}
        {job.queued_person_count > 0 ? (
          <span className="inline-flex items-center gap-1 text-sky-300">
            <Send className="h-3 w-3" aria-hidden />
            {job.queued_person_count} to approve
          </span>
        ) : job.person_count > 0 ? (
          <span className="inline-flex items-center gap-1">
            <Users className="h-3 w-3" aria-hidden />
            {job.person_count}
          </span>
        ) : null}
        {job.source && <span className="truncate">{job.source}</span>}
        <time className="ml-auto">{formatJobDate(job.updated_at)}</time>
      </div>
    </button>
  );
}
