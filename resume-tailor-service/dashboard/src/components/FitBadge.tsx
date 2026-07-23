// Fit is a free-text sheet field (e.g. "8", "8/10", "7 - good"). Parse the
// leading number for color; fall back to a neutral chip for anything else.
function fitClass(fit: string): string {
  const n = Number.parseFloat(fit);
  if (Number.isNaN(n)) return "bg-slate-800 text-slate-300 border-slate-700";
  if (n >= 8) return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  if (n >= 6) return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  return "bg-rose-500/15 text-rose-300 border-rose-500/30";
}

export default function FitBadge({ fit }: { fit: string }) {
  const label = fit && fit.trim() ? fit.trim() : "—";
  return (
    <span
      className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-semibold tabular-nums ${fitClass(
        fit
      )}`}
      title={`Fit: ${label}`}
    >
      {label}
    </span>
  );
}
