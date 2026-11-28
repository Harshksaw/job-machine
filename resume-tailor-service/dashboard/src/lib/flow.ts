// Pure helpers for the Flow tab. No React, so they run under node --test.
import type { FunnelNode, PipelineFunnel } from "../types";

export interface FlowRow {
  /** the path of keys from the top, joined with "/" */
  id: string;
  node: FunnelNode;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
}

/** The rows of the tree table: every top level row, and the children of each expanded
 * row whose parents are expanded too. */
export function visibleRows(nodes: FunnelNode[], expanded: Set<string>, depth = 0, parent = ""): FlowRow[] {
  const rows: FlowRow[] = [];
  for (const node of nodes) {
    const id = parent ? `${parent}/${node.key}` : node.key;
    const hasChildren = node.children.length > 0;
    const open = hasChildren && expanded.has(id);
    rows.push({ id, node, depth, hasChildren, expanded: open });
    if (open) rows.push(...visibleRows(node.children, expanded, depth + 1, id));
  }
  return rows;
}

export interface FlowPart {
  label: string;
  count: number;
}

export interface FlowStep {
  key: "source" | "region" | "eligibility" | "fit" | "packet" | "apply" | "outcome";
  title: string;
  explain: string;
  /** listings sitting at this step now */
  count: number;
  parts: FlowPart[];
}

function sum(stages: Record<string, number>, keys: string[]): number {
  return keys.reduce((total, key) => total + (stages[key] ?? 0), 0);
}

function parts(stages: Record<string, number>, entries: [string, string[]][]): FlowPart[] {
  return entries.map(([label, keys]) => ({ label, count: sum(stages, keys) }));
}

/** The guide: the current logic as one box per step, top to bottom, with live counts. */
export function flowSteps(funnel: PipelineFunnel): FlowStep[] {
  const s = funnel.stages;
  const harvest = funnel.harvest;
  const tiers = funnel.tiers;
  const sourceParts: FlowPart[] = [{ label: "Tracked now", count: funnel.total }];
  if (harvest) sourceParts.push({ label: "Fetched by the last harvest", count: harvest.fetched });
  const regionParts: FlowPart[] = [
    { label: "Tier A, open to Canada", count: tiers.A ?? 0 },
    { label: "Tier A2, US, UK, Australia, New Zealand or another country", count: tiers.A2 ?? 0 },
    { label: "Tier E, Europe (last)", count: tiers.E ?? 0 },
    { label: "Region unknown", count: tiers.unknown ?? 0 },
    { label: "Outside the region policy (India or not remote)", count: tiers.excluded ?? 0 },
  ];
  const tracked = regionParts.length;
  if (harvest) regionParts.push({ label: "Dropped by the filter", count: harvest.dropped });
  const eligibility = parts(s, [
    ["Waiting", ["research_new", "promoted", "discovered"]],
    ["Dismissed in research", ["dismissed"]],
    ["Ineligible", ["ineligible"]],
  ]);
  const fit = parts(s, [
    ["Retained, fit too low", ["retained"]],
    ["Eligible, fit 6 or more", ["eligible"]],
  ]);
  const packet = parts(s, [
    ["Run queued or running", ["in_pipeline"]],
    ["Run failed, needs a look", ["run_failed"]],
    ["Ready", ["ready"]],
    ["Packet ready", ["packet_ready"]],
  ]);
  const apply = parts(s, [
    ["Applying", ["applying"]],
    ["Applied", ["applied"]],
    ["Outreach", ["outreach"]],
  ]);
  const outcome = parts(s, [
    ["Interview", ["interview"]],
    ["Offer", ["offer"]],
    ["Rejected", ["rejected"]],
    ["Posting closed", ["closed"]],
  ]);
  const total = (list: FlowPart[]) => list.reduce((n, part) => n + part.count, 0);
  return [
    {
      key: "source",
      title: "1. Sources",
      explain:
        "Listings come from LinkedIn, Wellfound, YC, the remote boards and the ATS watchlist. Research finds wait for a yes before they become dossiers.",
      count: funnel.total,
      parts: sourceParts,
    },
    {
      key: "region",
      title: "2. Region filter",
      explain:
        "Remote only. Roles open to Canada or anywhere come first (A), then the US, UK, Australia, New Zealand or another country (A2, needs fit 7 or more), then Europe last (E). Senior titles and India based roles or employers are dropped.",
      count: total(regionParts.slice(0, tracked)),
      parts: regionParts,
    },
    {
      key: "eligibility",
      title: "3. Eligibility",
      explain:
        "A cheap model checks sponsorship, location and seniority against the policy. Ineligible runs stop with a reason; nothing is archived.",
      count: total(eligibility),
      parts: eligibility,
    },
    {
      key: "fit",
      title: "4. Fit score",
      explain: "Scored 1 to 10 against the resume bank. Under 6 (under 7 for Tier A2) is kept for review, not dropped.",
      count: total(fit),
      parts: fit,
    },
    {
      key: "packet",
      title: "5. Packet",
      explain: "Cover letter, form answers, people and a review. Packet ready means it waits for you to apply.",
      count: total(packet),
      parts: packet,
    },
    {
      key: "apply",
      title: "6. Apply",
      explain: "You submit. Nothing is ever sent without your yes.",
      count: total(apply),
      parts: apply,
    },
    {
      key: "outcome",
      title: "7. Outcome",
      explain: "Replies found by mail sync move the dossier on.",
      count: total(outcome),
      parts: outcome,
    },
  ];
}

export type RangePreset = "all" | "7d" | "30d";

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** since and until (ISO dates) for a quick range; "" means open ended. */
export function presetRange(preset: RangePreset, today: Date = new Date()): { since: string; until: string } {
  if (preset === "all") return { since: "", until: "" };
  const days = preset === "7d" ? 7 : 30;
  const start = new Date(today.getTime() - days * 24 * 60 * 60 * 1000);
  return { since: isoDate(start), until: "" };
}
