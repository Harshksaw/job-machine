import { useMemo } from "react";
import {
  Download,
  FileSpreadsheet,
  FilterX,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import type { Application } from "../types";
import { STATUS_ORDER, OTHER_COLUMN, statusStyle } from "../lib/status";

interface Props {
  apps: Application[];
  searchQuery: string;
  onSearchChange: (q: string) => void;
  statusFilter: string;
  onStatusChange: (status: string) => void;
  minFitFilter: number | null;
  onMinFitChange: (fit: number | null) => void;
  sourceFilter: string;
  onSourceChange: (source: string) => void;
  pdfOnlyFilter: boolean;
  onPdfOnlyChange: (pdfOnly: boolean) => void;
  onExportCSV: () => void;
  onExportJSON: () => void;
  onClearFilters: () => void;
}

export default function FilterBar({
  apps,
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusChange,
  minFitFilter,
  onMinFitChange,
  sourceFilter,
  onSourceChange,
  pdfOnlyFilter,
  onPdfOnlyChange,
  onExportCSV,
  onExportJSON,
  onClearFilters,
}: Props) {
  // Extract unique sources from apps
  const sources = useMemo(() => {
    const set = new Set<string>();
    for (const app of apps) {
      const src = (app.source || "").trim();
      if (src) set.add(src);
    }
    return Array.from(set).sort();
  }, [apps]);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (searchQuery.trim().length > 0) count++;
    if (statusFilter !== "all") count++;
    if (minFitFilter !== null) count++;
    if (sourceFilter !== "all") count++;
    if (pdfOnlyFilter) count++;
    return count;
  }, [searchQuery, statusFilter, minFitFilter, sourceFilter, pdfOnlyFilter]);

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-3 sm:flex-row sm:items-center sm:justify-between">
      {/* Left controls: Search & Filters */}
      <div className="flex flex-1 flex-wrap items-center gap-2">
        {/* Global Search input */}
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search
            className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
            aria-hidden
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search company, role, source, notes…"
            className="w-full rounded-lg border border-slate-800 bg-slate-950 py-1.5 pl-8 pr-7 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => onSearchChange("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              title="Clear search"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </div>

        {/* Status Dropdown */}
        <select
          value={statusFilter}
          onChange={(e) => onStatusChange(e.target.value)}
          className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
        >
          <option value="all">All Statuses</option>
          {STATUS_ORDER.map((key) => (
            <option key={key} value={key}>
              {statusStyle(key).label}
            </option>
          ))}
          <option value={OTHER_COLUMN.toLowerCase()}>Other</option>
        </select>

        {/* Min Fit Dropdown */}
        <select
          value={minFitFilter ?? "all"}
          onChange={(e) =>
            onMinFitChange(
              e.target.value === "all" ? null : Number(e.target.value)
            )
          }
          className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
        >
          <option value="all">All Fit Scores</option>
          <option value="6">Fit 6+ (Good)</option>
          <option value="8">Fit 8+ (High)</option>
          <option value="9">Fit 9+ (Top)</option>
        </select>

        {/* Source Dropdown */}
        {sources.length > 0 && (
          <select
            value={sourceFilter}
            onChange={(e) => onSourceChange(e.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-300 focus:border-indigo-500 focus:outline-none"
          >
            <option value="all">All Sources</option>
            {sources.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>
        )}

        {/* Tailored PDF Only Toggle */}
        <button
          type="button"
          onClick={() => onPdfOnlyChange(!pdfOnlyFilter)}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
            pdfOnlyFilter
              ? "border-purple-500/80 bg-purple-500/15 text-purple-300"
              : "border-slate-800 bg-slate-950 text-slate-400 hover:border-slate-700 hover:text-slate-300"
          }`}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          Tailored PDF Only
        </button>

        {/* Clear Filters Button */}
        {activeFilterCount > 0 && (
          <button
            type="button"
            onClick={onClearFilters}
            className="inline-flex items-center gap-1 rounded-lg border border-rose-500/30 bg-rose-500/10 px-2.5 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20"
          >
            <FilterX className="h-3.5 w-3.5" aria-hidden />
            Clear ({activeFilterCount})
          </button>
        )}
      </div>

      {/* Right controls: Data Export */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onExportCSV}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-700 hover:text-slate-100"
          title="Export currently filtered table data to CSV"
        >
          <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-400" aria-hidden />
          Export CSV
        </button>
        <button
          type="button"
          onClick={onExportJSON}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-700 hover:text-slate-100"
          title="Export currently filtered table data to JSON"
        >
          <Download className="h-3.5 w-3.5 text-sky-400" aria-hidden />
          Export JSON
        </button>
      </div>
    </div>
  );
}
