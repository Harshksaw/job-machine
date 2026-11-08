import { useCallback, useEffect, useState } from "react";
import { Bot, Play, Search as SearchIcon } from "lucide-react";
import {
  dismissResearch,
  listResearch,
  promoteResearch,
  type ResearchItem,
  getSearchOptions,
  getSearchUsage,
  listAgentRuns,
  runSearch,
  startAgent,
  type AgentRun,
  type SearchOptions,
  type SearchResult,
  type SearchUsage,
} from "../api";

interface Props {
  onJobsChanged: () => void;
  onOpenDossier: (jobId: string) => void;
}

export default function Search({ onJobsChanged, onOpenDossier }: Props) {
  const [options, setOptions] = useState<SearchOptions | null>(null);
  const [usage, setUsage] = useState<SearchUsage | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [limit, setLimit] = useState(20);
  const [timeFrame, setTimeFrame] = useState("7d");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [research, setResearch] = useState<ResearchItem[]>([]);
  const loadResearch = useCallback(() => listResearch().then(setResearch).catch(() => {}), []);

  const refresh = useCallback(async () => {
    try {
      const [o, u, r] = await Promise.all([getSearchOptions(), getSearchUsage(), listAgentRuns()]);
      setOptions(o);
      setUsage(u);
      setRuns(r);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load.");
    }
  }, []);

  useEffect(() => {
    void loadResearch();
  }, [loadResearch]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void listAgentRuns().then(setRuns).catch(() => {}), 10000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const search = async (preset: string) => {
    setBusy(preset);
    setMessage(null);
    try {
      const meta = options?.presets.find((p) => p.id === preset);
      const res = await runSearch(preset, meta?.stage === "research" ? meta.default_limit : limit, timeFrame);
      setResult(res);
      setUsage(res.usage);
      if (meta?.stage === "research") void loadResearch();
      else onJobsChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Search failed.");
    } finally {
      setBusy(null);
    }
  };

  const agent = async (tool: string, task: string) => {
    setBusy(`${tool}:${task}`);
    setMessage(null);
    try {
      const started = await startAgent(tool, task);
      setMessage(`Started ${tool} (pid ${started.pid}). Log: logs/agents/${started.log}`);
      setRuns(await listAgentRuns());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to start the agent.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="h-full space-y-4 overflow-y-auto">
      <section className="jm-panel space-y-3 p-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
            <SearchIcon className="h-4 w-4 text-teal-300" aria-hidden /> Fantastic Jobs
          </h2>
          {usage && (
            <p className="text-xs text-zinc-400 tabular-nums">
              {usage.jobs_left} of 500 trial jobs left · {usage.requests_left} of 100 requests left
              {!usage.configured && (
                <span className="ml-2 text-amber-300">
                  Add FANTASTIC_JOBS_API_KEY to resume-tailor-service/.env and restart the service
                </span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-400">
          <label className="flex items-center gap-2">
            Jobs per search
            <input
              type="number"
              min={1}
              max={50}
              value={limit}
              onChange={(e) => setLimit(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
              className="jm-input h-8 w-20"
            />
          </label>
          <label className="flex items-center gap-2">
            Posted within
            <select value={timeFrame} onChange={(e) => setTimeFrame(e.target.value)} className="jm-input h-8 w-24">
              <option value="24h">24 hours</option>
              <option value="7d">7 days</option>
            </select>
          </label>
          <span>Each search spends up to that many trial jobs. Known listings are skipped.</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {options?.presets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              disabled={busy !== null || !usage?.configured}
              onClick={() => void search(preset.id)}
              className="jm-btn-primary h-9 px-3 text-sm disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" aria-hidden />
              {busy === preset.id ? "Searching..." : preset.label}
            </button>
          ))}
        </div>
        {result && (
          <div className="space-y-1 text-sm">
            <p className="text-zinc-300">
              Fetched {result.fetched}: {result.new.length} new, {result.duplicates.length} already tracked.
            </p>
            <ul className="space-y-0.5">
              {result.new.map((job) => (
                <li key={job.id}>
                  <button
                    type="button"
                    onClick={() => onOpenDossier(job.id)}
                    className="text-left text-teal-300 hover:underline"
                  >
                    {job.company} · {job.role}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="jm-panel space-y-3 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
          <Bot className="h-4 w-4 text-teal-300" aria-hidden /> Agents
        </h2>
        <p className="text-xs text-zinc-400">
          Starts a fixed task in the background. Agents never submit applications or send outreach from here.
        </p>
        <div className="flex flex-wrap gap-2">
          {options?.tasks.flatMap((task) =>
            options.tools.map((tool) => (
              <button
                key={`${tool}:${task.id}`}
                type="button"
                disabled={busy !== null}
                onClick={() => void agent(tool, task.id)}
                className="jm-btn-secondary h-9 px-3 text-sm disabled:opacity-50"
              >
                {task.label} · {tool}
              </button>
            ))
          )}
        </div>
        {runs.length > 0 && (
          <div className="space-y-2">
            {runs.map((run) => (
              <details key={run.log} className="rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-xs">
                <summary className="cursor-pointer text-zinc-300">
                  {run.started} · {run.tool} · {run.task}
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-zinc-400">
                  {run.tail || "(no output yet)"}
                </pre>
              </details>
            ))}
          </div>
        )}
      </section>

      <section className="jm-panel space-y-2 p-4">
        <h2 className="text-sm font-semibold text-zinc-100">Research ({research.length} new)</h2>
        <p className="text-xs text-zinc-400">
          Staged finds from research presets and agent portal sweeps. Promote makes a discovered dossier; amber means the
          employer may not hire from Canada.
        </p>
        <ul className="divide-y divide-zinc-800">
          {research.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
              <a href={item.url} target="_blank" rel="noreferrer" className="font-medium text-zinc-100 hover:underline">
                {item.company} · {item.role}
              </a>
              <span className={item.open_to_canada ? "text-xs text-teal-300" : "text-xs text-amber-300"}>
                {item.remote_scope || "scope unspecified"}
              </span>
              <span className="text-xs text-zinc-500">
                {item.preset} {item.posted} {item.salary}
              </span>
              {item.tracked_dossier && <span className="text-xs text-zinc-500">already tracked</span>}
              <span className="ml-auto flex gap-2">
                <button
                  type="button"
                  className="jm-btn-secondary h-7 px-2 text-xs"
                  onClick={() => void promoteResearch(item.id).then(() => { void loadResearch(); onJobsChanged(); })}
                >
                  Promote
                </button>
                <button
                  type="button"
                  className="jm-btn-ghost h-7 px-2 text-xs"
                  onClick={() => void dismissResearch(item.id).then(() => void loadResearch())}
                >
                  Dismiss
                </button>
              </span>
            </li>
          ))}
        </ul>
      </section>

      {message && <p className="text-sm text-amber-300">{message}</p>}
    </div>
  );
}
