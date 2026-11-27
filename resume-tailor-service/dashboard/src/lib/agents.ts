// Pure helpers for the "Agents and models" settings. No React, so they run under
// node --test.
import type { AdapterSpec, PipelineCapability, PipelineConfig, StepPrefs } from "../types";

export const CAPABILITIES: PipelineCapability[] = ["cheap", "reason", "web", "browser_read"];

/** Turns a FastAPI error `detail` into readable lines: a string, a list of strings
 * (our step checks), or pydantic's list of {loc, msg}. */
export function formatApiDetail(detail: unknown): string[] {
  if (typeof detail === "string") return [detail];
  if (!Array.isArray(detail)) return [];
  return detail.map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item === "object") {
      const { loc, msg } = item as { loc?: unknown; msg?: unknown };
      const path = Array.isArray(loc) ? loc.filter((part) => part !== "body").join(".") : "";
      const text = typeof msg === "string" ? msg.replace(/^Value error, /, "") : "invalid value";
      return path ? `${path}: ${text}` : text;
    }
    return String(item);
  });
}

/** The config without its version stamp, for comparing a draft to what is saved. */
function body(config: PipelineConfig): string {
  const { version: _version, updated_at: _updated, ...rest } = config;
  return JSON.stringify(rest);
}

export function isDirty(saved: PipelineConfig | null, draft: PipelineConfig | null): boolean {
  if (!saved || !draft) return false;
  return body(saved) !== body(draft);
}

export function updateAdapter(
  config: PipelineConfig,
  name: string,
  patch: Partial<AdapterSpec>
): PipelineConfig {
  const current = config.adapters[name];
  if (!current) return config;
  return { ...config, adapters: { ...config.adapters, [name]: { ...current, ...patch } } };
}

/** Adds or removes a capability, keeping the canonical order. */
export function toggleCapability(
  capabilities: PipelineCapability[],
  capability: PipelineCapability
): PipelineCapability[] {
  const next = new Set(capabilities);
  if (next.has(capability)) next.delete(capability);
  else next.add(capability);
  return CAPABILITIES.filter((item) => next.has(item));
}

/** Enabled adapters that have a capability, cheapest first, then by name. Disabled
 * ones are left out: the router skips them, so picking one would do nothing. */
export function eligibleAdapters(config: PipelineConfig, capability: PipelineCapability): string[] {
  return Object.entries(config.adapters)
    .filter(([, spec]) => spec.enabled && spec.capabilities.includes(capability))
    .sort(([a, x], [b, y]) => x.cost_tier - y.cost_tier || a.localeCompare(b))
    .map(([name]) => name);
}

/** Sets one step's preferences. A step with no preference and no canary is dropped
 * so the saved config only lists real overrides. */
export function setStepPrefs(config: PipelineConfig, step: string, prefs: StepPrefs): PipelineConfig {
  const steps = { ...config.steps };
  if (prefs.prefer.length === 0 && !prefs.canary) delete steps[step];
  else steps[step] = prefs;
  return { ...config, steps };
}

export function stepPrefs(config: PipelineConfig, step: string): StepPrefs {
  return config.steps[step] ?? { prefer: [], canary: null };
}

/** Preferred or canary adapters for a step that are switched off, so the page can
 * warn that the router will skip them. */
export function disabledPicks(config: PipelineConfig, step: string): string[] {
  const prefs = stepPrefs(config, step);
  const picked = [...prefs.prefer, ...(prefs.canary ? [prefs.canary.adapter] : [])];
  return [...new Set(picked)].filter((name) => config.adapters[name] && !config.adapters[name].enabled);
}

/** Moves the item at `index` by `delta` places; out of range moves are ignored. */
export function moveItem<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (index < 0 || index >= items.length || target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** A percent typed in the form, as a 0 to 1 share. */
export function percentToShare(value: string): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n)) / 100;
}

export function shareToPercent(share: number): number {
  return Math.round(share * 1000) / 10;
}

/** Parses a whole number from an input, clamped to [min, max]; NaN keeps `fallback`. */
export function clampInt(value: string, min: number, max: number, fallback: number): number {
  const n = Number.parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}
