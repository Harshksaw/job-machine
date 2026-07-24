import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Columns3,
  Loader2,
  RefreshCw,
  Table2,
  Terminal,
  Users,
} from "lucide-react";
import type { Application, Person } from "./types";
import { fetchApplications, listPeople, resetBankCache } from "./api";
import { normalizeStatus } from "./lib/status";
import Board from "./components/Board";
import AppTable from "./components/AppTable";
import Inspector from "./components/Inspector";
import StatsHeader from "./components/StatsHeader";
import FilterBar from "./components/FilterBar";
import People from "./components/People";

type View = "board" | "table" | "people";
type LoadPhase = "loading" | "ready" | "error";

export default function App() {
  const [apps, setApps] = useState<Application[]>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [errorMsg, setErrorMsg] = useState("");

  const [people, setPeople] = useState<Person[]>([]);

  const [view, setView] = useState<View>("table");
  const [selected, setSelected] = useState<Application | null>(null);

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
    <div className="flex min-h-full flex-col bg-slate-950 text-slate-100">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-300">
            <Terminal className="h-4 w-4" aria-hidden />
          </span>
          <div>
            <h1 className="text-sm font-semibold leading-tight text-slate-100">
              Command Center
            </h1>
            <p className="text-xs text-slate-500">
              {phase === "ready"
                ? `${filteredApps.length} of ${apps.length} application${
                    apps.length === 1 ? "" : "s"
                  }`
                : "Job Machine dashboard"}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* View toggle */}
            <div className="flex rounded-lg border border-slate-800 bg-slate-900 p-0.5">
              <button
                type="button"
                onClick={() => setView("table")}
                aria-pressed={view === "table"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  view === "table"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Table2 className="h-3.5 w-3.5" aria-hidden />
                Table
              </button>
              <button
                type="button"
                onClick={() => setView("board")}
                aria-pressed={view === "board"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  view === "board"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Columns3 className="h-3.5 w-3.5" aria-hidden />
                Board
              </button>
              <button
                type="button"
                onClick={() => setView("people")}
                aria-pressed={view === "people"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  view === "people"
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Users className="h-3.5 w-3.5" aria-hidden />
                People
              </button>
            </div>

            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-700 hover:text-slate-100"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5 space-y-4">
        {phase === "loading" && (
          <div className="flex items-center justify-center gap-2 py-24 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            <span className="text-sm">Loading applications…</span>
          </div>
        )}

        {phase === "error" && (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <AlertTriangle className="h-8 w-8 text-rose-400" aria-hidden />
            <p className="text-sm text-slate-300">{errorMsg}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200 hover:border-slate-600"
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              Retry
            </button>
          </div>
        )}

        {phase === "ready" && (
          view === "people" ? (
            <People people={people} companies={companies} onChanged={loadPeople} />
          ) : (
            <>
              {/* Analytics Stats Header */}
              <StatsHeader
                apps={apps}
                activeStatusFilter={statusFilter}
                activeMinFit={minFitFilter}
                onSelectStatusFilter={setStatusFilter}
                onSelectMinFit={setMinFitFilter}
              />

              {/* Filter and Control Bar */}
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

              {/* Main Data Display */}
              {view === "table" ? (
                <AppTable
                  apps={filteredApps}
                  onOpen={setSelected}
                  onResetFilters={handleClearFilters}
                />
              ) : (
                <Board apps={filteredApps} onOpen={setSelected} />
              )}
            </>
          )
        )}
      </main>

      {selected && (
        <Inspector app={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
