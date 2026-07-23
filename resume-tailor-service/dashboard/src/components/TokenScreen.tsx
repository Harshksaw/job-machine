import { useState } from "react";
import { KeyRound, ShieldAlert, Terminal } from "lucide-react";

interface Props {
  onSubmit: (token: string) => void;
  error?: string | null;
}

export default function TokenScreen({ onSubmit, error }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (trimmed) onSubmit(trimmed);
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900/60 p-6 shadow-xl shadow-black/30"
      >
        <div className="mb-5 flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/15 text-indigo-300">
            <Terminal className="h-5 w-5" aria-hidden />
          </span>
          <div>
            <h1 className="text-base font-semibold text-slate-100">
              Command Center
            </h1>
            <p className="text-xs text-slate-500">Job Machine dashboard</p>
          </div>
        </div>

        <label
          htmlFor="token"
          className="mb-1.5 block text-sm font-medium text-slate-300"
        >
          Access token
        </label>
        <div className="relative">
          <KeyRound
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500"
            aria-hidden
          />
          <input
            id="token"
            type="password"
            autoComplete="off"
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Bearer token"
            className="w-full rounded-lg border border-slate-700 bg-slate-950/80 py-2 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        {error && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-rose-300">
            <ShieldAlert className="h-3.5 w-3.5" aria-hidden />
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={!value.trim()}
          className="mt-5 w-full rounded-lg bg-indigo-500 py-2 text-sm font-semibold text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Connect
        </button>

        <p className="mt-4 text-center text-xs text-slate-600">
          The token is stored only in this browser and sent as a bearer header.
        </p>
      </form>
    </div>
  );
}
