import { useMemo } from "react";
import {
  Briefcase,
  CheckCircle2,
  FileCheck,
  Flame,
  TrendingUp,
} from "lucide-react";
import type { Application } from "../types";
import { normalizeStatus } from "../lib/status";

interface Props {
  apps: Application[];
  activeStatusFilter: string;
  activeMinFit: number | null;
  onSelectStatusFilter: (status: string) => void;
  onSelectMinFit: (fit: number | null) => void;
}

export default function StatsHeader({
  apps,
  activeStatusFilter,
  activeMinFit,
  onSelectStatusFilter,
  onSelectMinFit,
}: Props) {
  const stats = useMemo(() => {
    const total = apps.length;
    let appliedCount = 0;
    let interviewCount = 0;
    let repliedCount = 0;
    let highFitCount = 0;
    let pdfCount = 0;

    for (const app of apps) {
      const st = normalizeStatus(app.status);
      if (st === "applied" || st === "outreach-sent" || st === "people-mined") {
        appliedCount++;
      }
      if (st === "interview") {
        interviewCount++;
      }
      if (st === "replied" || st === "interview") {
        repliedCount++;
      }
      const fitNum = Number.parseFloat(app.fit);
      if (!Number.isNaN(fitNum) && fitNum >= 8) {
        highFitCount++;
      }
      if (app.tailored_resume_id) {
        pdfCount++;
      }
    }

    const responseRate = total > 0 ? Math.round((repliedCount / total) * 100) : 0;

    return {
      total,
      appliedCount,
      interviewCount,
      repliedCount,
      highFitCount,
      pdfCount,
      responseRate,
    };
  }, [apps]);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {/* Card 1: Total Applications */}
      <button
        type="button"
        onClick={() => onSelectStatusFilter("all")}
        className={`flex flex-col gap-1 rounded-xl border p-3.5 text-left transition ${
          activeStatusFilter === "all" && activeMinFit === null
            ? "border-indigo-500/80 bg-indigo-500/10 ring-1 ring-indigo-500/40"
            : "border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/80"
        }`}
      >
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Total Applications</span>
          <Briefcase className="h-4 w-4 text-indigo-400" />
        </div>
        <div className="text-2xl font-bold tracking-tight text-slate-100">
          {stats.total}
        </div>
        <div className="text-[11px] text-slate-500">All logged entries</div>
      </button>

      {/* Card 2: Interviews */}
      <button
        type="button"
        onClick={() =>
          onSelectStatusFilter(
            activeStatusFilter === "interview" ? "all" : "interview"
          )
        }
        className={`flex flex-col gap-1 rounded-xl border p-3.5 text-left transition ${
          activeStatusFilter === "interview"
            ? "border-emerald-500/80 bg-emerald-500/10 ring-1 ring-emerald-500/40"
            : "border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/80"
        }`}
      >
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Interviews</span>
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        </div>
        <div className="text-2xl font-bold tracking-tight text-emerald-300">
          {stats.interviewCount}
        </div>
        <div className="text-[11px] text-emerald-400/80">Active pipeline</div>
      </button>

      {/* Card 3: Response Rate */}
      <div className="flex flex-col gap-1 rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 text-left">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Response Rate</span>
          <TrendingUp className="h-4 w-4 text-cyan-400" />
        </div>
        <div className="text-2xl font-bold tracking-tight text-cyan-300">
          {stats.responseRate}%
        </div>
        <div className="text-[11px] text-slate-500">
          {stats.repliedCount} responses
        </div>
      </div>

      {/* Card 4: High Fit (8+) */}
      <button
        type="button"
        onClick={() => onSelectMinFit(activeMinFit === 8 ? null : 8)}
        className={`flex flex-col gap-1 rounded-xl border p-3.5 text-left transition ${
          activeMinFit === 8
            ? "border-amber-500/80 bg-amber-500/10 ring-1 ring-amber-500/40"
            : "border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/80"
        }`}
      >
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>High Fit (8+)</span>
          <Flame className="h-4 w-4 text-amber-400" />
        </div>
        <div className="text-2xl font-bold tracking-tight text-amber-300">
          {stats.highFitCount}
        </div>
        <div className="text-[11px] text-amber-400/80">Top targets</div>
      </button>

      {/* Card 5: Tailored PDFs */}
      <div className="col-span-2 flex flex-col gap-1 rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 text-left sm:col-span-1">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>Tailored PDFs</span>
          <FileCheck className="h-4 w-4 text-purple-400" />
        </div>
        <div className="text-2xl font-bold tracking-tight text-purple-300">
          {stats.pdfCount}
        </div>
        <div className="text-[11px] text-slate-500">Generated & stored</div>
      </div>
    </div>
  );
}
