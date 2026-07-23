import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ExternalLink, FileCheck2 } from "lucide-react";
import type { Application } from "../types";
import { normalizeStatus, statusStyle } from "../lib/status";
import FitBadge from "./FitBadge";

interface Props {
  apps: Application[];
  onOpen: (app: Application) => void;
}

type SortKey = "company" | "role" | "status" | "fit" | "source";

function sortValue(app: Application, key: SortKey): string | number {
  if (key === "fit") {
    const n = Number.parseFloat(app.fit);
    return Number.isNaN(n) ? -Infinity : n;
  }
  if (key === "status") return normalizeStatus(app.status);
  return (app[key] || "").toLowerCase();
}

export default function AppTable({ apps, onOpen }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("company");
  const [asc, setAsc] = useState(true);

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

  function toggleSort(key: SortKey) {
    if (key === sortKey) setAsc((v) => !v);
    else {
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
  ];

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
            {columns.map((col) => (
              <th key={col.key} className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort(col.key)}
                  className="inline-flex items-center gap-1 hover:text-slate-200"
                >
                  {col.label}
                  {sortKey === col.key &&
                    (asc ? (
                      <ArrowUp className="h-3 w-3" aria-hidden />
                    ) : (
                      <ArrowDown className="h-3 w-3" aria-hidden />
                    ))}
                </button>
              </th>
            ))}
            <th className="px-3 py-2 font-medium">PDF</th>
            <th className="px-3 py-2 font-medium">Link</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((app, i) => {
            const st = statusStyle(normalizeStatus(app.status));
            const hasUrl = app.job_url.trim().length > 0;
            return (
              <tr
                key={`${app.company}-${app.role}-${i}`}
                onClick={() => onOpen(app)}
                className="cursor-pointer border-b border-slate-800/60 last:border-0 hover:bg-slate-900/60"
              >
                <td className="px-3 py-2 font-medium text-slate-100">
                  {app.company || "—"}
                </td>
                <td className="px-3 py-2 text-slate-300">{app.role || "—"}</td>
                <td className="px-3 py-2">
                  <span
                    className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs ${st.chip}`}
                  >
                    {st.label}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <FitBadge fit={app.fit} />
                </td>
                <td className="px-3 py-2 text-slate-400">{app.source || "—"}</td>
                <td className="px-3 py-2">
                  {app.tailored_resume_id != null ? (
                    <FileCheck2
                      className="h-4 w-4 text-emerald-300"
                      aria-label="Tailored PDF available"
                    />
                  ) : (
                    <span className="text-slate-600">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {hasUrl ? (
                    <a
                      href={app.job_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex text-slate-400 hover:text-indigo-300"
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
  );
}
