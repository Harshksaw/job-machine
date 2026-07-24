import { ExternalLink, FileCheck2, Users } from "lucide-react";
import type { Application, Person } from "../types";
import { matchesApplication } from "../lib/people";
import FitBadge from "./FitBadge";

interface Props {
  app: Application;
  people: Person[];
  onOpen: (app: Application) => void;
}

export default function AppCard({ app, people, onOpen }: Props) {
  const hasPdf = app.tailored_resume_id != null;
  const hasUrl = app.job_url.trim().length > 0;
  const peopleCount = people.filter((p) =>
    matchesApplication(p, { company: app.company, role: app.role })
  ).length;

  return (
    <button
      type="button"
      onClick={() => onOpen(app)}
      className="group w-full rounded-lg border border-slate-800 bg-slate-900/70 p-3 text-left transition hover:border-slate-600 hover:bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-100">
            {app.company || "Unknown company"}
          </div>
          <div className="mt-0.5 truncate text-xs text-slate-400">
            {app.role || "—"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {peopleCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-400">
              <Users className="h-3 w-3" aria-hidden /> {peopleCount}
            </span>
          )}
          <FitBadge fit={app.fit} />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs">
        {hasPdf && (
          <span className="inline-flex items-center gap-1 font-medium text-emerald-300">
            <FileCheck2 className="h-3.5 w-3.5" aria-hidden />
            PDF
          </span>
        )}
        {hasUrl && (
          <a
            href={app.job_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-slate-400 hover:text-indigo-300"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            Job
          </a>
        )}
        {app.source.trim() && (
          <span className="ml-auto truncate text-slate-500" title={app.source}>
            {app.source}
          </span>
        )}
      </div>
    </button>
  );
}
