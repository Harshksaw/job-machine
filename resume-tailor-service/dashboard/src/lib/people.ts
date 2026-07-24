import type { Person } from "../types";

export const PERSON_STATUSES = ["to-reach", "queued", "sent", "replied", "skip"] as const;

export const STATUS_LABEL: Record<string, string> = {
  "to-reach": "To reach", queued: "Queued", sent: "Sent", replied: "Replied", skip: "Skip",
};

export const STATUS_STYLE: Record<string, string> = {
  "to-reach": "bg-amber-500/15 text-amber-300 border-amber-500/30",
  queued: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  sent: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
  replied: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  skip: "bg-slate-600/20 text-slate-400 border-slate-600/40",
};

const ORDER = new Map<string, number>(PERSON_STATUSES.map((s, i) => [s, i]));
export function statusRank(s: string): number {
  return ORDER.get(s) ?? PERSON_STATUSES.length;
}

export function companyKey(company: string): string {
  return company.trim().toLowerCase();
}

/** True when a person should show under an application row. Company-level match;
 * when the person pinned a role, require that too. */
export function matchesApplication(p: Person, app: { company: string; role: string }): boolean {
  if (companyKey(p.company) !== companyKey(app.company)) return false;
  if (p.role && p.role.trim()) return companyKey(p.role) === companyKey(app.role);
  return true;
}

/** Only http(s) links are safe to render as hrefs. */
export function safeHref(url: string): string | null {
  const u = url.trim();
  return /^https?:\/\//i.test(u) ? u : null;
}
