import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Bot, History, RefreshCw, X } from "lucide-react";
import {
  ApiError,
  PipelineError,
  getPipelineConfig,
  listPipelineAdapters,
  listPipelineSteps,
  listPipelineVersions,
  resetPipelineConfig,
  rollbackPipelineConfig,
  savePipelineConfig,
  testPipelineAdapter,
} from "../api";
import {
  CAPABILITIES,
  clampInt,
  eligibleAdapters,
  isDirty,
  moveItem,
  percentToShare,
  setStepPrefs,
  shareToPercent,
  stepPrefs,
  toggleCapability,
  updateAdapter,
} from "../lib/agents";
import type { AdapterStatus, PipelineConfig, PipelineStep, PipelineVersion } from "../types";

const HEADING = "flex items-center gap-2 border-b border-zinc-600 pb-2 text-sm font-semibold text-zinc-100";

function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function errorLines(error: unknown, fallback: string): string[] {
  if (error instanceof PipelineError) return error.lines;
  if (error instanceof ApiError || error instanceof Error) return [error.message];
  return [fallback];
}

function LastTest({ status }: { status: AdapterStatus | undefined }) {
  const last = status?.last_test;
  if (!last) return <span className="text-zinc-600">never</span>;
  const ok = last.outcome === "ok";
  return (
    <span title={last.error || undefined}>
      <span className={ok ? "text-teal-300" : "text-rose-300"}>{ok ? "Passed" : last.outcome}</span>
      <span className="text-zinc-500"> · {when(last.at)}</span>
      {last.error && <span className="block max-w-[16rem] truncate text-zinc-500">{last.error}</span>}
    </span>
  );
}

export default function AgentsSettings() {
  const [saved, setSaved] = useState<PipelineConfig | null>(null);
  const [draft, setDraft] = useState<PipelineConfig | null>(null);
  const [adapters, setAdapters] = useState<Record<string, AdapterStatus>>({});
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [versions, setVersions] = useState<PipelineVersion[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<Set<string>>(new Set());

  const loadStatus = useCallback(async () => {
    const [rows, history] = await Promise.all([listPipelineAdapters(), listPipelineVersions()]);
    setAdapters(Object.fromEntries(rows.map((row) => [row.name, row])));
    setVersions(history);
  }, []);

  const adopt = useCallback((config: PipelineConfig) => {
    setSaved(config);
    setDraft(config);
  }, []);

  const load = useCallback(async () => {
    setErrors([]);
    try {
      const [config, stepRows] = await Promise.all([getPipelineConfig(), listPipelineSteps()]);
      adopt(config);
      setSteps(stepRows);
      await loadStatus();
    } catch (error) {
      setErrors(errorLines(error, "Failed to load agent settings."));
    }
  }, [adopt, loadStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = isDirty(saved, draft);

  // Runs a write that returns the new effective config, then refreshes status and history.
  const write = async (action: () => Promise<PipelineConfig>, done: string) => {
    setBusy(true);
    setErrors([]);
    setNotice(null);
    try {
      const config = await action();
      adopt(config);
      setNotice(`${done} Now on version ${config.version}.`);
      await loadStatus();
    } catch (error) {
      setErrors(errorLines(error, "Request failed."));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (draft) void write(() => savePipelineConfig(draft), "Saved.");
  };

  const rollback = (version: number) => {
    const lose = dirty ? " Your unsaved changes will be lost." : "";
    if (!window.confirm(`Go back to the settings from version ${version}? This saves them as a new version.${lose}`)) return;
    void write(() => rollbackPipelineConfig(version), `Rolled back to version ${version}.`);
  };

  const reset = () => {
    if (!window.confirm("Replace the current settings with the defaults from content/agents.yaml? The current ones stay in the history.")) return;
    void write(resetPipelineConfig, "Reset to defaults.");
  };

  const runTest = async (name: string) => {
    setTesting((current) => new Set(current).add(name));
    try {
      await testPipelineAdapter(name);
    } catch (error) {
      setErrors(errorLines(error, `Test of ${name} failed.`));
    }
    try {
      await loadStatus();
    } catch {
      // the next load shows it
    }
    setTesting((current) => {
      const next = new Set(current);
      next.delete(name);
      return next;
    });
  };

  if (!draft || !saved) {
    return (
      <section className="jm-panel p-4">
        <h2 className={HEADING}>
          <Bot className="h-4 w-4 text-teal-300" aria-hidden /> Agents and models
        </h2>
        {errors.length > 0 ? (
          <ul className="mt-3 space-y-0.5 text-sm text-amber-300">
            {errors.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-xs text-zinc-500">Loading agent settings...</p>
        )}
      </section>
    );
  }

  const names = Object.keys(draft.adapters);

  return (
    <section className="jm-panel p-4" aria-label="Agents and models">
      <div className={`${HEADING} flex-wrap`}>
        <Bot className="h-4 w-4 text-teal-300" aria-hidden /> Agents and models
        <span className="text-xs font-normal text-zinc-500">
          Version {saved.version}, saved {when(saved.updated_at)}
          {dirty && <span className="text-amber-300"> · unsaved changes</span>}
        </span>
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={() => void load()} disabled={busy} className="jm-btn-ghost h-8 px-2 text-xs">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Reload
          </button>
          <button type="button" onClick={reset} disabled={busy} className="jm-btn-secondary h-8 px-3 text-xs">
            Reset to defaults
          </button>
          <button
            type="button"
            onClick={() => setDraft(saved)}
            disabled={busy || !dirty}
            className="jm-btn-secondary h-8 px-3 text-xs"
          >
            Discard changes
          </button>
          <button type="button" onClick={save} disabled={busy || !dirty} className="jm-btn-primary h-8 px-3 text-xs">
            Save
          </button>
        </div>
      </div>

      <p className="mt-2 text-xs text-zinc-500">
        Saved settings apply to the next step without a restart. Keys stay in .env; this page only shows whether each
        one is set. Test runs one tiny call with the saved settings, even for a disabled adapter.
      </p>

      {errors.length > 0 && (
        <div role="alert" className="mt-3 rounded-md border border-rose-900 bg-rose-950/40 p-2.5 text-sm text-rose-200">
          <p className="font-medium">That did not work:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
            {errors.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {notice && <p className="mt-3 text-sm text-teal-300">{notice}</p>}

      <label className="mt-3 flex items-center gap-2 text-sm text-zinc-300">
        Workers
        <input
          type="number"
          min={0}
          max={32}
          value={draft.workers}
          onChange={(event) =>
            setDraft({ ...draft, workers: clampInt(event.target.value, 0, 32, draft.workers) })
          }
          className="jm-input h-8 w-20 py-1"
        />
        <span className="text-xs text-zinc-500">runs at once</span>
      </label>

      <h3 className="jm-section-title mt-4">Adapters</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              <th className="pb-1 pr-2 font-medium">On</th>
              <th className="pb-1 pr-2 font-medium">Adapter</th>
              <th className="pb-1 pr-2 font-medium">Model or command</th>
              <th className="pb-1 pr-2 font-medium">Capabilities</th>
              <th className="pb-1 pr-2 font-medium">Cost tier</th>
              <th className="pb-1 pr-2 font-medium">Max parallel</th>
              <th className="pb-1 pr-2 font-medium">Key</th>
              <th className="pb-1 pr-2 font-medium">Health</th>
              <th className="pb-1 pr-2 font-medium">Last test</th>
              <th className="pb-1 font-medium" />
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            {names.map((name) => {
              const spec = draft.adapters[name];
              const status = adapters[name];
              const set = (patch: Partial<typeof spec>) => setDraft(updateAdapter(draft, name, patch));
              const isTesting = testing.has(name);
              return (
                <tr key={name} className="align-top">
                  <td className="py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={spec.enabled}
                      onChange={(event) => set({ enabled: event.target.checked })}
                      aria-label={`${name} enabled`}
                      className="mt-1.5 accent-teal-500"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <span className="font-medium text-zinc-100">{name}</span>
                    <span className="block text-xs text-zinc-500">
                      {spec.type}
                      {spec.provider ? ` · ${spec.provider}` : ""}
                    </span>
                  </td>
                  <td className="py-2 pr-2">
                    {spec.type === "cli" ? (
                      <code
                        className="block max-w-[18rem] truncate pt-1 text-xs text-zinc-400"
                        title={spec.command.join(" ")}
                      >
                        {spec.command.join(" ")}
                      </code>
                    ) : (
                      <input
                        value={spec.model}
                        onChange={(event) => set({ model: event.target.value })}
                        aria-label={`${name} model`}
                        className="jm-input h-8 min-w-[14rem] py-1 font-mono text-xs"
                      />
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    <div className="flex flex-wrap gap-1">
                      {CAPABILITIES.map((capability) => {
                        const on = spec.capabilities.includes(capability);
                        return (
                          <button
                            key={capability}
                            type="button"
                            aria-pressed={on}
                            onClick={() => set({ capabilities: toggleCapability(spec.capabilities, capability) })}
                            className={`rounded border px-1.5 py-0.5 text-[11px] ${
                              on
                                ? "border-teal-700 bg-teal-950 text-teal-200"
                                : "border-zinc-800 text-zinc-600 hover:text-zinc-400"
                            }`}
                          >
                            {capability}
                          </button>
                        );
                      })}
                    </div>
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      min={0}
                      max={10}
                      value={spec.cost_tier}
                      onChange={(event) => set({ cost_tier: clampInt(event.target.value, 0, 10, spec.cost_tier) })}
                      aria-label={`${name} cost tier`}
                      className="jm-input h-8 w-16 py-1"
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="number"
                      min={1}
                      max={32}
                      value={spec.max_parallel}
                      onChange={(event) =>
                        set({ max_parallel: clampInt(event.target.value, 1, 32, spec.max_parallel) })
                      }
                      aria-label={`${name} max parallel`}
                      className="jm-input h-8 w-16 py-1"
                    />
                  </td>
                  <td className="py-2 pr-2 text-xs">
                    {!spec.key_env ? (
                      <span className="text-zinc-500">not needed</span>
                    ) : status?.key_set ? (
                      <span className="text-teal-300" title={spec.key_env}>
                        Yes
                      </span>
                    ) : (
                      <span className="text-amber-300" title={`Set ${spec.key_env} in .env`}>
                        No ({spec.key_env})
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-xs">
                    {!status ? (
                      <span className="text-zinc-600">unknown</span>
                    ) : status.health.healthy ? (
                      <span className="text-teal-300">Healthy</span>
                    ) : (
                      <span className="text-rose-300" title={status.health.reason}>
                        Unhealthy
                        <span className="block max-w-[12rem] truncate text-zinc-500">{status.health.reason}</span>
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-xs">{isTesting ? "Testing..." : <LastTest status={status} />}</td>
                  <td className="py-2">
                    <button
                      type="button"
                      onClick={() => void runTest(name)}
                      disabled={isTesting || !(name in saved.adapters)}
                      className="jm-btn-ghost h-7 px-2 text-xs"
                    >
                      Test
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h3 className="jm-section-title mt-5">Steps</h3>
      <p className="-mt-1 mb-2 text-xs text-zinc-500">
        Preferred adapters go first, in this order. Other enabled adapters with the capability follow, cheapest first. A
        canary sends a share of runs to one adapter so a new model can be tried on live work.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-zinc-500">
            <tr>
              <th className="pb-1 pr-2 font-medium">Step</th>
              <th className="pb-1 pr-2 font-medium">Needs</th>
              <th className="pb-1 pr-2 font-medium">Preferred adapters</th>
              <th className="pb-1 font-medium">Canary</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800 text-zinc-300">
            {steps.map(({ step, capability }) => {
              const prefs = stepPrefs(draft, step);
              const options = eligibleAdapters(draft, capability);
              const addable = options.filter((name) => !prefs.prefer.includes(name));
              const setPrefs = (next: typeof prefs) => setDraft(setStepPrefs(draft, step, next));
              return (
                <tr key={step} className="align-top">
                  <td className="py-2 pr-2 font-medium text-zinc-100">{step}</td>
                  <td className="py-2 pr-2 text-xs text-zinc-400">{capability}</td>
                  <td className="py-2 pr-2">
                    <ol className="flex flex-wrap items-center gap-1">
                      {prefs.prefer.map((name, index) => (
                        <li
                          key={name}
                          className="inline-flex items-center gap-0.5 rounded border border-zinc-700 py-0.5 pl-1.5 pr-0.5 text-xs"
                        >
                          <span className="text-zinc-500">{index + 1}.</span> {name}
                          <button
                            type="button"
                            onClick={() => setPrefs({ ...prefs, prefer: moveItem(prefs.prefer, index, -1) })}
                            disabled={index === 0}
                            aria-label={`Move ${name} up for ${step}`}
                            className="rounded p-0.5 text-zinc-500 hover:text-zinc-200 disabled:opacity-30"
                          >
                            <ArrowUp className="h-3 w-3" aria-hidden />
                          </button>
                          <button
                            type="button"
                            onClick={() => setPrefs({ ...prefs, prefer: moveItem(prefs.prefer, index, 1) })}
                            disabled={index === prefs.prefer.length - 1}
                            aria-label={`Move ${name} down for ${step}`}
                            className="rounded p-0.5 text-zinc-500 hover:text-zinc-200 disabled:opacity-30"
                          >
                            <ArrowDown className="h-3 w-3" aria-hidden />
                          </button>
                          <button
                            type="button"
                            onClick={() => setPrefs({ ...prefs, prefer: prefs.prefer.filter((item) => item !== name) })}
                            aria-label={`Remove ${name} from ${step}`}
                            className="rounded p-0.5 text-zinc-500 hover:text-rose-300"
                          >
                            <X className="h-3 w-3" aria-hidden />
                          </button>
                        </li>
                      ))}
                      {addable.length > 0 && (
                        <li>
                          <select
                            value=""
                            onChange={(event) => {
                              if (event.target.value) setPrefs({ ...prefs, prefer: [...prefs.prefer, event.target.value] });
                            }}
                            aria-label={`Add a preferred adapter for ${step}`}
                            className="jm-input h-7 w-auto py-0 text-xs"
                          >
                            <option value="">Add...</option>
                            {addable.map((name) => (
                              <option key={name} value={name}>
                                {name}
                              </option>
                            ))}
                          </select>
                        </li>
                      )}
                      {prefs.prefer.length === 0 && addable.length === 0 && (
                        <li className="text-xs text-zinc-600">no adapter has {capability}</li>
                      )}
                    </ol>
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1.5">
                      <select
                        value={prefs.canary?.adapter ?? ""}
                        onChange={(event) =>
                          setPrefs({
                            ...prefs,
                            canary: event.target.value
                              ? { adapter: event.target.value, share: prefs.canary?.share ?? 0.1 }
                              : null,
                          })
                        }
                        aria-label={`Canary adapter for ${step}`}
                        className="jm-input h-7 w-auto py-0 text-xs"
                      >
                        <option value="">None</option>
                        {options.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                      </select>
                      {prefs.canary && (
                        <label className="flex items-center gap-1 text-xs text-zinc-400">
                          <input
                            type="number"
                            min={0}
                            max={100}
                            step={5}
                            value={shareToPercent(prefs.canary.share)}
                            onChange={(event) =>
                              setPrefs({
                                ...prefs,
                                canary: { adapter: prefs.canary!.adapter, share: percentToShare(event.target.value) },
                              })
                            }
                            aria-label={`Canary share for ${step}`}
                            className="jm-input h-7 w-16 py-0 text-xs"
                          />
                          % of runs
                        </label>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h3 className="jm-section-title mt-5">
        <History className="h-3.5 w-3.5" aria-hidden /> Version history
      </h3>
      <ul className="max-h-60 divide-y divide-zinc-800 overflow-y-auto">
        {versions.map((row) => {
          const current = row.version === saved.version;
          return (
            <li key={row.version} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
              <span className="w-12 shrink-0 font-medium tabular-nums text-zinc-100">v{row.version}</span>
              <span className="w-36 shrink-0 text-xs text-zinc-500">{when(row.updated_at)}</span>
              <span className="min-w-0 flex-1 text-zinc-400">{row.note || "saved"}</span>
              {current ? (
                <span className="text-xs text-teal-300">current</span>
              ) : (
                <button
                  type="button"
                  onClick={() => rollback(row.version)}
                  disabled={busy}
                  className="jm-btn-ghost h-7 px-2 text-xs"
                >
                  Rollback
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
