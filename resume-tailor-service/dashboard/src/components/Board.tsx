import type { Application, Person } from "../types";
import { groupByStatus } from "../lib/status";
import AppCard from "./AppCard";

interface Props {
  apps: Application[];
  people: Person[];
  onOpen: (app: Application) => void;
}

export default function Board({ apps, people, onOpen }: Props) {
  const columns = groupByStatus(apps);

  return (
    <div className="flex gap-4 overflow-x-auto pb-4">
      {columns.map((col) => (
        <section
          key={col.key}
          className="flex w-72 shrink-0 flex-col rounded-xl border border-slate-800/80 bg-slate-900/30"
        >
          <header className="flex items-center gap-2 border-b border-slate-800/80 px-3 py-2.5">
            <span className={`h-2 w-2 rounded-full ${col.style.dot}`} aria-hidden />
            <h2 className="text-sm font-semibold text-slate-200">
              {col.style.label}
            </h2>
            <span className="ml-auto rounded-full bg-slate-800 px-2 py-0.5 text-xs tabular-nums text-slate-400">
              {col.items.length}
            </span>
          </header>

          <div className="flex flex-1 flex-col gap-2 p-2">
            {col.items.length === 0 ? (
              <p className="px-1 py-6 text-center text-xs text-slate-600">
                Empty
              </p>
            ) : (
              col.items.map((app, i) => (
                <AppCard
                  key={`${app.company}-${app.role}-${i}`}
                  app={app}
                  people={people}
                  onOpen={onOpen}
                />
              ))
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
