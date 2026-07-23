import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Columns3,
  Loader2,
  LogOut,
  RefreshCw,
  Table2,
  Terminal,
} from "lucide-react";
import type { Application } from "./types";
import {
  UNAUTHORIZED_EVENT,
  clearToken,
  fetchApplications,
  getToken,
  resetBankCache,
  setToken as persistToken,
} from "./api";
import TokenScreen from "./components/TokenScreen";
import Board from "./components/Board";
import AppTable from "./components/AppTable";
import Inspector from "./components/Inspector";

type View = "board" | "table";
type LoadPhase = "loading" | "ready" | "error";

export default function App() {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [authError, setAuthError] = useState<string | null>(null);

  const [apps, setApps] = useState<Application[]>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [errorMsg, setErrorMsg] = useState("");

  const [view, setView] = useState<View>("board");
  const [selected, setSelected] = useState<Application | null>(null);

  // Any 401 clears the token and returns us to the token screen.
  useEffect(() => {
    const onUnauthorized = () => {
      setTokenState(null);
      setSelected(null);
      resetBankCache();
      setAuthError("Your token was rejected. Please enter a valid token.");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const data = await fetchApplications();
      setApps(data);
      setPhase("ready");
    } catch (err) {
      // 401 is handled by the global listener (drops to token screen).
      setErrorMsg(err instanceof Error ? err.message : "Failed to load.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    if (token) void load();
  }, [token, load]);

  const handleToken = useCallback((value: string) => {
    persistToken(value);
    setAuthError(null);
    setTokenState(value);
  }, []);

  const handleSignOut = useCallback(() => {
    clearToken();
    resetBankCache();
    setSelected(null);
    setApps([]);
    setTokenState(null);
    setAuthError(null);
  }, []);

  if (!token) {
    return <TokenScreen onSubmit={handleToken} error={authError} />;
  }

  return (
    <div className="flex min-h-full flex-col">
      {/* Top bar */}
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-3 px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-300">
            <Terminal className="h-4 w-4" aria-hidden />
          </span>
          <div>
            <h1 className="text-sm font-semibold leading-tight text-slate-100">
              Command Center
            </h1>
            <p className="text-xs text-slate-500">
              {phase === "ready"
                ? `${apps.length} application${apps.length === 1 ? "" : "s"}`
                : "Job Machine dashboard"}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* View toggle */}
            <div className="flex rounded-lg border border-slate-800 bg-slate-900 p-0.5">
              <button
                type="button"
                onClick={() => setView("board")}
                aria-pressed={view === "board"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  view === "board"
                    ? "bg-slate-700 text-slate-100"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Columns3 className="h-3.5 w-3.5" aria-hidden />
                Board
              </button>
              <button
                type="button"
                onClick={() => setView("table")}
                aria-pressed={view === "table"}
                className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  view === "table"
                    ? "bg-slate-700 text-slate-100"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Table2 className="h-3.5 w-3.5" aria-hidden />
                Table
              </button>
            </div>

            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-700 hover:text-slate-100"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Refresh
            </button>

            <button
              type="button"
              onClick={handleSignOut}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:border-rose-500/40 hover:text-rose-300"
              title="Sign out / change token"
            >
              <LogOut className="h-3.5 w-3.5" aria-hidden />
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-5">
        {phase === "loading" && (
          <div className="flex items-center justify-center gap-2 py-24 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            <span className="text-sm">Loading applications…</span>
          </div>
        )}

        {phase === "error" && (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <AlertTriangle className="h-8 w-8 text-rose-400" aria-hidden />
            <p className="text-sm text-slate-300">{errorMsg}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200 hover:border-slate-600"
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              Retry
            </button>
          </div>
        )}

        {phase === "ready" &&
          (apps.length === 0 ? (
            <div className="py-24 text-center text-sm text-slate-500">
              No applications logged yet.
            </div>
          ) : view === "board" ? (
            <Board apps={apps} onOpen={setSelected} />
          ) : (
            <AppTable apps={apps} onOpen={setSelected} />
          ))}
      </main>

      {selected && (
        <Inspector app={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
