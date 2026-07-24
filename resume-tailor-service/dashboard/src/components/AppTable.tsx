import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Calendar,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileCheck2,
  Inbox,
} from "lucide-react";
import type { Application } from "../types";
import { normalizeStatus, statusStyle } from "../lib/status";
import FitBadge from "./FitBadge";

interface Props {
  apps: Application[];
  onOpen: (app: Application) => void;
  onResetFilters?: () => void;
}

export type SortKey =
  | "company"
  | "role"
  | "status"
  | "fit"
  | "source"
  | "timestamp"
  | "pdf";

function sortValue(app: Application, key: SortKey): string | number {
  if (key === "fit") {
    const n = Number.parseFloat(app.fit);
    return Number.isNaN(n) ? -Infinity : n;
  }
  if (key === "status") return normalizeStatus(app.status);
  if (key === "pdf") return app.tailored_resume_id ? 1 : 0;
  return (app[key] || "").toLowerCase();
}

function formatDate(ts: string): string {
  if (!ts || !ts.trim()) return "—";
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return ts;
  }
}

export default function AppTable({ apps, onOpen, onResetFilters }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("company");
  const [asc, setAsc] = useState(true);

  // Pagination state
  const [pageSize, setPageSize] = useState<number>(25);
  const [currentPage, setCurrentPage] = useState<number>(1);

  // Sort applications
  const sorted = useMemo(() => {
    const copy = [...apps];
    copy.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    return copy;
  }, [apps, sortKey, asc]);

  // Compute pagination
  const totalItems = sorted.length;
  const isAll = pageSize === -1;
  const totalPages = isAll ? 1 : Math.max(1, Math.ceil(totalItems / pageSize));
  const safePage = Math.min(currentPage, totalPages);

  const paginated = useMemo(() => {
    if (isAll) return sorted;
    const start = (safePage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, safePage, pageSize, isAll]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setAsc((v) => !v);
    } else {
      setSortKey(key);
      setAsc(true);
    }
  }

  const columns: { key: SortKey; label: string }[] = [
    { key: "company", label: "Company" },
    { key: "role", label: "Role" },
    { key: "status", label: "Status" },
    { key: "fit", label: "Fit" },
    { key: "source", label: "Source" },
    { key: "timestamp", label: "Date" },
    { key: "pdf", label: "Tailored PDF" },
  ];

  const startIndex = isAll ? 1 : (safePage - 1) * pageSize + 1;
  const endIndex = isAll ? totalItems : Math.min(safePage * pageSize, totalItems);

  if (totalItems === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-slate-800 bg-slate-900/30 py-16 text-center">
        <Inbox className="h-10 w-10 text-slate-600" aria-hidden />
        <p className="text-sm font-medium text-slate-300">
          No matching applications found
        </p>
        <p className="text-xs text-slate-500">
          Try clearing search keywords or adjusting your status and fit filters.
        </p>
        {onResetFilters && (
          <button
            type="button"
            onClick={onResetFilters}
            className="mt-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700"
          >
            Reset Filters
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Table Container */}
      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/60 shadow-inner">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/80 text-xs uppercase tracking-wider text-slate-400">
              {columns.map((col) => (
                <th key={col.key} className="px-3.5 py-3 font-medium">
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="inline-flex items-center gap-1 hover:text-slate-100"
                  >
                    {col.label}
                    {sortKey === col.key &&
                      (asc ? (
                        <ArrowUp className="h-3 w-3 text-indigo-400" aria-hidden />
                      ) : (
                        <ArrowDown className="h-3 w-3 text-indigo-400" aria-hidden />
                      ))}
                  </button>
                </th>
              ))}
              <th className="px-3.5 py-3 font-medium text-slate-400">Link</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {paginated.map((app, i) => {
              const st = statusStyle(normalizeStatus(app.status));
              const hasUrl = app.job_url.trim().length > 0;
              return (
                <tr
                  key={`${app.company}-${app.role}-${i}`}
                  onClick={() => onOpen(app)}
                  className="group cursor-pointer transition hover:bg-slate-900/80"
                >
                  {/* Company */}
                  <td className="px-3.5 py-2.5 font-semibold text-slate-100 group-hover:text-indigo-300">
                    {app.company || "—"}
                  </td>
                  {/* Role */}
                  <td className="px-3.5 py-2.5 text-slate-300">{app.role || "—"}</td>
                  {/* Status */}
                  <td className="px-3.5 py-2.5">
                    <span
                      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${st.chip}`}
                    >
                      {st.label}
                    </span>
                  </td>
                  {/* Fit */}
                  <td className="px-3.5 py-2.5">
                    <FitBadge fit={app.fit} />
                  </td>
                  {/* Source */}
                  <td className="px-3.5 py-2.5 text-slate-400">{app.source || "—"}</td>
                  {/* Date */}
                  <td className="px-3.5 py-2.5 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <Calendar className="h-3 w-3 text-slate-600" aria-hidden />
                      {formatDate(app.timestamp)}
                    </span>
                  </td>
                  {/* Tailored PDF */}
                  <td className="px-3.5 py-2.5">
                    {app.tailored_resume_id != null ? (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">
                        <FileCheck2 className="h-3.5 w-3.5" aria-hidden />
                        Ready
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  {/* Link */}
                  <td className="px-3.5 py-2.5">
                    {hasUrl ? (
                      <a
                        href={app.job_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-indigo-300"
                        aria-label="Open job posting"
                      >
                        <ExternalLink className="h-4 w-4" aria-hidden />
                      </a>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="flex flex-col gap-2 px-1 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">
        <div>
          Showing <span className="font-semibold text-slate-200">{startIndex}</span> to{" "}
          <span className="font-semibold text-slate-200">{endIndex}</span> of{" "}
          <span className="font-semibold text-slate-200">{totalItems}</span> applications
        </div>

        <div className="flex items-center gap-3">
          {/* Rows per page selector */}
          <div className="flex items-center gap-1.5">
            <span>Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setCurrentPage(1);
              }}
              className="rounded border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-200 focus:border-indigo-500 focus:outline-none"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={-1}>All</option>
            </select>
          </div>

          {/* Page Buttons */}
          {!isAll && totalPages > 1 && (
            <div className="flex items-center gap-1">
              <button
                type="button"
                disabled={safePage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-800 bg-slate-900 text-slate-300 disabled:opacity-40 hover:enabled:border-slate-700 hover:enabled:bg-slate-800"
                title="Previous page"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>

              <span className="px-2 font-medium text-slate-300">
                Page {safePage} of {totalPages}
              </span>

              <button
                type="button"
                disabled={safePage >= totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-800 bg-slate-900 text-slate-300 disabled:opacity-40 hover:enabled:border-slate-700 hover:enabled:bg-slate-800"
                title="Next page"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
