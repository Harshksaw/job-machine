import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BriefcaseBusiness,
  Columns3,
  Inbox as InboxIcon,
  RefreshCw,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { JobSummary, Person } from "./types";
import { listJobs, listPeople } from "./api";
import { inInboxQueue } from "./lib/jobs";
import Board from "./components/Board";
import People from "./components/People";
import JobWorkspace from "./components/JobWorkspace";
import Inbox from "./components/Inbox";

type View = "inbox" | "workspace" | "board" | "people";

const VIEW_COPY: Record<View, { title: string; subtitle: string }> = {
  inbox: { title: "Inbox", subtitle: "Decisions and approvals waiting on you" },
  workspace: { title: "Dossiers", subtitle: "Every job record, kit, and activity log" },
  board: { title: "Board", subtitle: "Pipeline by stage" },
  people: { title: "People", subtitle: "Outreach contacts and drafts" },
};

const CLOSED = new Set(["rejected", "skipped", "archived"]);

function viewFromHash(): View {
  const head = window.location.hash.replace(/^#/, "").split("/")[0];
  return head === "workspace" || head === "board" || head === "people" ? head : "inbox";
}

export default function App() {
  const [view, setView] = useState<View>(viewFromHash);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [workspaceFocusId, setWorkspaceFocusId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch {
      /* the views surface their own load errors */
    }
  }, []);

  const loadPeople = useCallback(async () => {
    try {
      setPeople(await listPeople());
    } catch {
      /* the People view shows an empty state */
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([loadJobs(), loadPeople()]);
    setRefreshing(false);
  }, [loadJobs, loadPeople]);

  useEffect(() => {
    const onHash = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    void refreshAll();
    const timer = window.setInterval(() => void loadJobs(), 20000);
    return () => window.clearInterval(timer);
  }, [refreshAll, loadJobs]);

  const go = useCallback((next: View) => {
    setView(next);
    if (viewFromHash() !== next || !window.location.hash) {
      window.history.pushState(null, "", `#${next}`);
    }
  }, []);

  const openDossier = useCallback(
    (jobId: string) => {
      setWorkspaceFocusId(jobId);
      go("workspace");
    },
    [go]
  );

  const consumeWorkspaceFocus = useCallback(() => setWorkspaceFocusId(null), []);

  const companies = useMemo(
    () => Array.from(new Set(jobs.map((job) => job.company).filter(Boolean))).sort(),
    [jobs]
  );

  const counts = useMemo(
    () => ({
      inbox: jobs.filter((job) => inInboxQueue(job, "needs-you")).length,
      workspace: jobs.filter((job) => !CLOSED.has(job.status)).length,
      board: jobs.filter((job) => job.status === "applied").length,
      people: people.filter((person) => person.status === "queued").length,
    }),
    [jobs, people]
  );

  const nav: { id: View; label: string; icon: LucideIcon; count: number; hint: string }[] = [
    { id: "inbox", label: "Inbox", icon: InboxIcon, count: counts.inbox, hint: "need you" },
    { id: "workspace", label: "Dossiers", icon: BriefcaseBusiness, count: counts.workspace, hint: "active" },
    { id: "board", label: "Board", icon: Columns3, count: counts.board, hint: "applied" },
    { id: "people", label: "People", icon: Users, count: counts.people, hint: "to approve" },
  ];

  const copy = VIEW_COPY[view];

  return (
    <div className="flex h-full flex-col bg-canvas text-ink lg:flex-row">
      <a href="#content" className="skip-link">
        Skip to content
      </a>

      <aside className="flex shrink-0 flex-col border-b border-zinc-800 bg-surface lg:h-full lg:w-60 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-4 py-3 lg:px-5 lg:py-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-600 text-white">
            <BriefcaseBusiness className="h-4 w-4" aria-hidden />
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-zinc-50">
            Job Machine
          </span>
          <button
            type="button"
            onClick={() => void refreshAll()}
            className="jm-icon-btn ml-auto lg:hidden"
            aria-label="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden />
          </button>
        </div>

        <nav
          aria-label="Primary"
          className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible lg:pb-0"
        >
          {nav.map((item) => {
            const Icon = item.icon;
            const active = view === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => go(item.id)}
                aria-current={active ? "page" : undefined}
                title={`${item.count} ${item.hint}`}
                className={`group flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  active
                    ? "bg-zinc-800 text-zinc-50"
                    : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                }`}
              >
                <Icon
                  className={`h-4 w-4 ${active ? "text-teal-300" : "text-zinc-500 group-hover:text-zinc-300"}`}
                  aria-hidden
                />
                {item.label}
                {item.count > 0 && (
                  <span
                    className={`ml-auto rounded-full px-1.5 text-xs tabular-nums ${
                      item.id === "inbox" || item.id === "people"
                        ? "bg-teal-600/20 text-teal-200"
                        : "text-zinc-500"
                    }`}
                  >
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="mt-auto hidden px-5 py-4 lg:block">
          <button
            type="button"
            onClick={() => void refreshAll()}
            className="jm-btn-ghost h-8 w-full justify-start px-2 text-xs text-zinc-500"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} aria-hidden />
            {jobs.length} dossiers · refresh
          </button>
        </div>
      </aside>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex items-baseline gap-3 border-b border-zinc-800 px-4 py-3 lg:px-6 lg:py-4">
          <h1 className="text-lg font-semibold tracking-tight text-zinc-50">{copy.title}</h1>
          <p className="truncate text-sm text-zinc-500">{copy.subtitle}</p>
        </header>

        <main id="content" tabIndex={-1} className="min-h-0 flex-1 overflow-hidden p-3 lg:p-4">
          {view === "inbox" ? (
            <Inbox
              onOpenDossier={openDossier}
              onPeopleChanged={() => void refreshAll()}
              onJobsChanged={() => void loadJobs()}
            />
          ) : view === "workspace" ? (
            <JobWorkspace
              focusJobId={workspaceFocusId}
              onFocusConsumed={consumeWorkspaceFocus}
              onPeopleChanged={() => void refreshAll()}
            />
          ) : view === "board" ? (
            <Board jobs={jobs} onOpen={openDossier} />
          ) : (
            <div className="h-full overflow-y-auto">
              <People people={people} companies={companies} onChanged={() => void refreshAll()} />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
