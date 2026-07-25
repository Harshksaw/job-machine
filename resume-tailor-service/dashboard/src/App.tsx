import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BriefcaseBusiness,
  Columns3,
  Loader2,
  RefreshCw,
  Table2,
  Users,
} from "lucide-react";
import type { Application, Person } from "./types";
import {
  createJobFromApplication,
  fetchApplications,
  listPeople,
  resetBankCache,
} from "./api";
import { normalizeStatus } from "./lib/status";
import Board from "./components/Board";
import AppTable from "./components/AppTable";
import Inspector from "./components/Inspector";
import StatsHeader from "./components/StatsHeader";
import FilterBar from "./components/FilterBar";
import People from "./components/People";
import JobWorkspace from "./components/JobWorkspace";

type View = "workspace" | "board" | "table" | "people";
type LoadPhase = "loading" | "ready" | "error";

const NAV_ITEMS = [
  { id: "workspace" as const, label: "Dossiers", icon: BriefcaseBusiness },
  { id: "table" as const, label: "Pipeline", icon: Table2 },
  { id: "board" as const, label: "Board", icon: Columns3 },
  { id: "people" as const, label: "People", icon: Users },
];

export default function App() {
  const [apps, setApps] = useState<Application[]>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [errorMsg, setErrorMsg] = useState("");

  const [people, setPeople] = useState<Person[]>([]);

  const [view, setView] = useState<View>("workspace");
  const [selected, setSelected] = useState<Application | null>(null);
  const [workspaceFocusId, setWorkspaceFocusId] = useState<string | null>(null);

  // Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [minFitFilter, setMinFitFilter] = useState<number | null>(null);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [pdfOnlyFilter, setPdfOnlyFilter] = useState(false);

  const load = useCallback(async () => {
    setPhase("loading");
    resetBankCache();
    try {
      const data = await fetchApplications();
      setApps(data);
      setPhase("ready");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to load.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadPeople = useCallback(async () => {
    try {
      setPeople(await listPeople());
    } catch {
      /* non-fatal for the board */
    }
  }, []);

  useEffect(() => {
    void loadPeople();
  }, [loadPeople]);

  const openWorkspaceForApplication = useCallback(
    async (application: Application) => {
      const job = await createJobFromApplication(application, "Pipeline");
      setWorkspaceFocusId(job.id);
      setSelected(null);
      setView("workspace");
    },
    []
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([load(), loadPeople()]);
  }, [load, loadPeople]);

  const consumeWorkspaceFocus = useCallback(() => {
    setWorkspaceFocusId(null);
  }, []);

  const companies = useMemo(
    () => Array.from(new Set(apps.map((a) => a.company).filter(Boolean))).sort(),
    [apps]
  );

  const handleClearFilters = useCallback(() => {
    setSearchQuery("");
    setStatusFilter("all");
    setMinFitFilter(null);
    setSourceFilter("all");
    setPdfOnlyFilter(false);
  }, []);

  const filteredApps = useMemo(() => {
    return apps.filter((app) => {
      // Search query
      if (searchQuery.trim().length > 0) {
        const q = searchQuery.trim().toLowerCase();
        const matchCompany = (app.company || "").toLowerCase().includes(q);
        const matchRole = (app.role || "").toLowerCase().includes(q);
        const matchSource = (app.source || "").toLowerCase().includes(q);
        const matchNotes = (app.notes || "").toLowerCase().includes(q);
        const matchHooks = (app.hooks || "").toLowerCase().includes(q);
        const matchPeople = (app.people || "").toLowerCase().includes(q);
        if (
          !matchCompany &&
          !matchRole &&
          !matchSource &&
          !matchNotes &&
          !matchHooks &&
          !matchPeople
        ) {
          return false;
        }
      }

      // Status filter
      if (statusFilter !== "all") {
        const norm = normalizeStatus(app.status);
        if (norm !== statusFilter) return false;
      }

      // Min Fit filter
      if (minFitFilter !== null) {
        const fitNum = Number.parseFloat(app.fit);
        if (Number.isNaN(fitNum) || fitNum < minFitFilter) return false;
      }

      // Source filter
      if (sourceFilter !== "all") {
        if ((app.source || "").trim() !== sourceFilter) return false;
      }

      // Tailored PDF filter
      if (pdfOnlyFilter) {
        if (!app.tailored_resume_id) return false;
      }

      return true;
    });
  }, [apps, searchQuery, statusFilter, minFitFilter, sourceFilter, pdfOnlyFilter]);

  const handleExportCSV = useCallback(() => {
    const headers = [
      "Company",
      "Role",
      "Status",
      "Fit",
      "Source",
      "Job URL",
      "Timestamp",
      "Has Tailored PDF",
      "Notes",
    ];
    const rows = filteredApps.map((a) => [
      `"${(a.company || "").replace(/"/g, '""')}"`,
      `"${(a.role || "").replace(/"/g, '""')}"`,
      `"${(a.status || "").replace(/"/g, '""')}"`,
      `"${(a.fit || "").replace(/"/g, '""')}"`,
      `"${(a.source || "").replace(/"/g, '""')}"`,
      `"${(a.job_url || "").replace(/"/g, '""')}"`,
      `"${(a.timestamp || "").replace(/"/g, '""')}"`,
      `"${a.tailored_resume_id ? "Yes" : "No"}"`,
      `"${(a.notes || "").replace(/"/g, '""')}"`,
    ]);
    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute(
      "download",
      `applications_${new Date().toISOString().slice(0, 10)}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [filteredApps]);

  const handleExportJSON = useCallback(() => {
    const blob = new Blob([JSON.stringify(filteredApps, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute(
      "download",
      `applications_${new Date().toISOString().slice(0, 10)}.json`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }, [filteredApps]);

  return (
    <div className="flex min-h-full flex-col bg-zinc-950 text-zinc-100">
      <header className="sticky top-0 z-20 border-b border-zinc-800 bg-zinc-950/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-3 px-3 py-2.5 sm:px-4">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-teal-800/70 bg-teal-950/40 text-teal-300">
            <BriefcaseBusiness className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold leading-tight text-zinc-100">
              Job Machine
            </h1>
            <p className="truncate text-xs text-zinc-600">
              {view === "workspace"
                ? "Private application workspace"
                : view === "people"
                  ? `${people.length} outreach contact${people.length === 1 ? "" : "s"}`
                  : phase === "ready"
                    ? `${filteredApps.length} of ${apps.length} application${
                        apps.length === 1 ? "" : "s"
                      }`
                    : "Application pipeline"}
            </p>
          </div>

          <div className="order-3 flex w-full items-center gap-2 sm:order-none sm:ml-auto sm:w-auto">
            <div className="flex min-w-0 flex-1 overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 p-0.5 sm:flex-none">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setView(item.id)}
                    aria-pressed={view === item.id}
                    className={`inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition ${
                      view === item.id
                        ? "bg-teal-700 text-white"
                        : "text-zinc-500 hover:text-zinc-200"
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    {item.label}
                  </button>
                );
              })}
            </div>
            {view !== "workspace" && (
              <button
                type="button"
                onClick={() => void refreshAll()}
                className="rounded-md border border-zinc-800 bg-zinc-900 p-2 text-zinc-500 hover:border-zinc-700 hover:text-zinc-100"
                title="Refresh"
                aria-label="Refresh"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </header>

      <main
        className={`mx-auto w-full max-w-[1680px] flex-1 px-3 sm:px-4 ${
          view === "workspace" ? "py-3" : "space-y-4 py-5"
        }`}
      >
        {view === "workspace" ? (
          <JobWorkspace
            people={people}
            focusJobId={workspaceFocusId}
            onFocusConsumed={consumeWorkspaceFocus}
          />
        ) : view === "people" ? (
          <People people={people} companies={companies} onChanged={loadPeople} />
        ) : phase === "loading" ? (
          <div className="flex items-center justify-center gap-2 py-24 text-zinc-500">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            <span className="text-sm">Loading applications...</span>
          </div>
        ) : phase === "error" ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <AlertTriangle className="h-8 w-8 text-rose-400" aria-hidden />
            <p className="text-sm text-zinc-300">{errorMsg}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 hover:border-zinc-600"
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              Retry
            </button>
          </div>
        ) : (
          <>
            <StatsHeader
              apps={apps}
              activeStatusFilter={statusFilter}
              activeMinFit={minFitFilter}
              onSelectStatusFilter={setStatusFilter}
              onSelectMinFit={setMinFitFilter}
            />
            <FilterBar
              apps={apps}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
              statusFilter={statusFilter}
              onStatusChange={setStatusFilter}
              minFitFilter={minFitFilter}
              onMinFitChange={setMinFitFilter}
              sourceFilter={sourceFilter}
              onSourceChange={setSourceFilter}
              pdfOnlyFilter={pdfOnlyFilter}
              onPdfOnlyChange={setPdfOnlyFilter}
              onExportCSV={handleExportCSV}
              onExportJSON={handleExportJSON}
              onClearFilters={handleClearFilters}
            />
            {view === "table" ? (
              <AppTable
                apps={filteredApps}
                onOpen={setSelected}
                onResetFilters={handleClearFilters}
              />
            ) : (
              <Board apps={filteredApps} people={people} onOpen={setSelected} />
            )}
          </>
        )}
      </main>

      {selected && (
        <Inspector
          app={selected}
          people={people}
          onClose={() => setSelected(null)}
          onOpenWorkspace={() => openWorkspaceForApplication(selected)}
          onAddPerson={(company, role) => {
            setSelected(null);
            setView("people");
            // People view exposes its own Add button; the company/role are visible
            // on the row the user just came from. (A prefilled deep-link is a later nicety.)
            void role;
            void company;
          }}
        />
      )}
    </div>
  );
}
