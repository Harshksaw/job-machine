import type { Application } from "../types";

// Canonical workflow order (from the project's application lifecycle).
export const STATUS_ORDER = [
  "applied",
  "people-mined",
  "outreach-sent",
  "outreach-queued",
  "replied",
  "interview",
  "rejected",
] as const;

export const OTHER_COLUMN = "Other";

type StatusStyle = { label: string; dot: string; chip: string };

const STATUS_STYLES: Record<string, StatusStyle> = {
  applied: {
    label: "Applied",
    dot: "bg-sky-400",
    chip: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  },
  "people-mined": {
    label: "People Mined",
    dot: "bg-violet-400",
    chip: "bg-violet-500/10 text-violet-300 border-violet-500/30",
  },
  "outreach-sent": {
    label: "Outreach Sent",
    dot: "bg-cyan-400",
    chip: "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
  },
  "outreach-queued": {
    label: "Outreach Queued",
    dot: "bg-amber-400",
    chip: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  },
  replied: {
    label: "Replied",
    dot: "bg-teal-400",
    chip: "bg-teal-500/10 text-teal-300 border-teal-500/30",
  },
  interview: {
    label: "Interview",
    dot: "bg-emerald-400",
    chip: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  },
  rejected: {
    label: "Rejected",
    dot: "bg-rose-400",
    chip: "bg-rose-500/10 text-rose-300 border-rose-500/30",
  },
};

const OTHER_STYLE: StatusStyle = {
  label: "Other",
  dot: "bg-slate-500",
  chip: "bg-slate-700/40 text-slate-300 border-slate-600/40",
};

/** Normalize a raw sheet status to a canonical key, or OTHER_COLUMN. */
export function normalizeStatus(raw: string): string {
  const key = (raw || "").trim().toLowerCase();
  return (STATUS_ORDER as readonly string[]).includes(key) ? key : OTHER_COLUMN;
}

export function statusStyle(key: string): StatusStyle {
  return STATUS_STYLES[key] ?? OTHER_STYLE;
}

export interface StatusColumn {
  key: string;
  style: StatusStyle;
  items: Application[];
}

/** Group applications into columns in canonical order, appending a trailing
 * "Other" column only when it actually has rows. */
export function groupByStatus(apps: Application[]): StatusColumn[] {
  const buckets = new Map<string, Application[]>();
  for (const key of STATUS_ORDER) buckets.set(key, []);

  for (const app of apps) {
    const key = normalizeStatus(app.status);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(app);
  }

  const columns: StatusColumn[] = STATUS_ORDER.map((key) => ({
    key,
    style: statusStyle(key),
    items: buckets.get(key) ?? [],
  }));

  const other = buckets.get(OTHER_COLUMN) ?? [];
  if (other.length > 0) {
    columns.push({ key: OTHER_COLUMN, style: OTHER_STYLE, items: other });
  }
  return columns;
}
