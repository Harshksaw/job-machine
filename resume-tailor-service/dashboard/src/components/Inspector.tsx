import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BriefcaseBusiness,
  ExternalLink,
  FileText,
  Layers,
  Linkedin,
  Loader2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import type { Application, Person, ResumeBank, TailoredResumeMeta } from "../types";
import { fetchTailored, loadResumeBank } from "../api";
import { matchesApplication, safeHref, STATUS_LABEL, STATUS_STYLE } from "../lib/people";

interface Props {
  app: Application;
  people: Person[];
  onClose: () => void;
  onAddPerson: (company: string, role: string) => void;
  onOpenWorkspace: () => Promise<void>;
}

type Phase = "loading" | "ready" | "error";

interface ResolvedGroup {
  heading: string;
  subheading?: string;
  bullets: string[];
}

function resolveManifest(
  meta: TailoredResumeMeta,
  bank: ResumeBank
): {
  jobs: ResolvedGroup[];
  projects: ResolvedGroup[];
  achievements: string[];
  skills: string[];
} {
  const jobById = new Map(bank.jobs.map((j) => [j.id, j]));
  const projById = new Map(bank.projects.map((p) => [p.id, p]));
  const achById = new Map(bank.achievements.map((a) => [a.id, a]));

  const jobs = meta.manifest.job_selections.map((sel) => {
    const job = jobById.get(sel.job_id);
    const bulletById = new Map((job?.bullets ?? []).map((b) => [b.id, b]));
    return {
      heading: job?.title ?? sel.job_id,
      subheading: job?.company,
      bullets: sel.bullet_ids.map(
        (id) => bulletById.get(id)?.text ?? `[missing bullet: ${id}]`
      ),
    };
  });

  const projects = meta.manifest.project_selections.map((sel) => {
    const proj = projById.get(sel.project_id);
    const bulletById = new Map((proj?.bullets ?? []).map((b) => [b.id, b]));
    return {
      heading: proj?.name ?? sel.project_id,
      bullets: sel.bullet_ids.map(
        (id) => bulletById.get(id)?.text ?? `[missing bullet: ${id}]`
      ),
    };
  });

  const achievements = meta.manifest.achievement_ids.map(
    (id) => achById.get(id)?.text ?? `[missing achievement: ${id}]`
  );
  const skillById = new Map(bank.skills.map((skill) => [skill.id, skill]));
  const skillIds =
    meta.manifest.skill_ids.length > 0
      ? meta.manifest.skill_ids
      : bank.skills.map((skill) => skill.id);
  const skills = skillIds.map((id) => {
    const skill = skillById.get(id);
    return skill ? `${skill.category}: ${skill.items}` : `[missing skill: ${id}]`;
  });

  return { jobs, projects, achievements, skills };
}

function PeoplePanel({
  app,
  people,
  onAddPerson,
}: {
  app: Application;
  people: Person[];
  onAddPerson: (c: string, r: string) => void;
}) {
  const matched = people.filter((p) =>
    matchesApplication(p, { company: app.company, role: app.role })
  );
  const hooks = app.hooks.trim();
  const rawPeople = app.people.trim();
  const chip =
    "inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300";
  return (
    <section className="border-t border-slate-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Users className="h-4 w-4 text-slate-400" aria-hidden /> People at{" "}
          {app.company || "this company"}
        </h3>
        <button
          type="button"
          onClick={() => onAddPerson(app.company, app.role)}
          className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300"
        >
          <UserPlus className="h-3.5 w-3.5" /> Add
        </button>
      </div>
      {matched.length > 0 ? (
        <ul className="space-y-2">
          {matched.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-slate-100">{p.name}</span>
              {p.title && <span className="text-slate-500">· {p.title}</span>}
              <span
                className={`inline-flex rounded-md border px-1.5 py-0.5 text-xs ${
                  STATUS_STYLE[p.status] ?? ""
                }`}
              >
                {STATUS_LABEL[p.status] ?? p.status}
              </span>
              {safeHref(p.linkedin_url) && (
                <a
                  className={chip}
                  href={safeHref(p.linkedin_url)!}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Linkedin className="h-3 w-3" /> LinkedIn
                </a>
              )}
              {p.links.map(
                (l, i) =>
                  safeHref(l.url) && (
                    <a
                      key={i}
                      className={chip}
                      href={safeHref(l.url)!}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <ExternalLink className="h-3 w-3" /> {l.label || "link"}
                    </a>
                  )
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-600">No people added for this company yet.</p>
      )}
      {(hooks || rawPeople) && (
        <div className="mt-4 grid gap-3 text-xs text-slate-500 sm:grid-cols-2">
          {hooks && (
            <div>
              <div className="mb-1 uppercase tracking-wide">Hooks (sheet)</div>
              <p className="whitespace-pre-wrap text-slate-400">{hooks}</p>
            </div>
          )}
          {rawPeople && (
            <div>
              <div className="mb-1 uppercase tracking-wide">Raw sheet note</div>
              <p className="whitespace-pre-wrap text-slate-400">{rawPeople}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ManifestGroup({ group }: { group: ResolvedGroup }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
      <div className="text-sm font-medium text-slate-200">
        {group.heading}
        {group.subheading && (
          <span className="text-slate-500"> · {group.subheading}</span>
        )}
      </div>
      <ul className="mt-2 space-y-1.5">
        {group.bullets.map((text, i) => (
          <li key={i} className="flex gap-2 text-sm text-slate-300">
            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-indigo-400" aria-hidden />
            <span className="break-words">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Inspector({
  app,
  people,
  onClose,
  onAddPerson,
  onOpenWorkspace,
}: Props) {
  const id = app.tailored_resume_id;

  const [phase, setPhase] = useState<Phase>("loading");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [meta, setMeta] = useState<TailoredResumeMeta | null>(null);
  const [bank, setBank] = useState<ResumeBank | null>(null);
  const [openingWorkspace, setOpeningWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Load metadata + resume bank (bank is cached across opens).
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setPhase("loading");
    Promise.all([fetchTailored(id), loadResumeBank()])
      .then(([m, b]) => {
        if (cancelled) return;
        setMeta(m);
        setBank(b);
        setPhase("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setErrorMsg(err instanceof Error ? err.message : "Failed to load.");
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const resolved = useMemo(
    () => (meta && bank ? resolveManifest(meta, bank) : null),
    [meta, bank]
  );

  const openWorkspace = async () => {
    setOpeningWorkspace(true);
    setWorkspaceError("");
    try {
      await onOpenWorkspace();
    } catch (err) {
      setWorkspaceError(
        err instanceof Error ? err.message : "Failed to open job dossier."
      );
      setOpeningWorkspace(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/70 p-0 sm:p-4"
      onClick={onClose}
    >
      <div
        className="flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-none border-slate-800 bg-slate-950 shadow-2xl sm:rounded-lg sm:border"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Resume inspector for ${app.company}`}
      >
        {/* Header */}
        <header className="flex items-center gap-3 border-b border-slate-800 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-100">
              {app.company || "Unknown company"}
            </h2>
            <p className="truncate text-xs text-slate-400">{app.role || "—"}</p>
          </div>
          {meta && (
            <span className="ml-2 inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs text-slate-300">
              <FileText className="h-3.5 w-3.5" aria-hidden />
              {meta.pages} {meta.pages === 1 ? "page" : "pages"}
            </span>
          )}
          {safeHref(app.job_url) && (
            <a
              href={safeHref(app.job_url)!}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-indigo-300"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              Job
            </a>
          )}
          <button
            type="button"
            onClick={() => void openWorkspace()}
            disabled={openingWorkspace}
            className="inline-flex items-center gap-1.5 rounded-md bg-teal-700 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-teal-600 disabled:opacity-50"
          >
            {openingWorkspace ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <BriefcaseBusiness className="h-3.5 w-3.5" />
            )}
            Dossier
          </button>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            aria-label="Close inspector"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>

        {workspaceError && (
          <div className="border-b border-rose-900/60 bg-rose-950/30 px-4 py-2 text-xs text-rose-300">
            {workspaceError}
          </div>
        )}

        {/* Body */}
        {id == null ? (
          <div className="flex flex-1 flex-col">
            <div className="flex flex-1 flex-col items-center justify-center gap-2 p-10 text-center">
              <FileText className="h-8 w-8 text-slate-600" aria-hidden />
              <p className="text-sm text-slate-400">
                No tailored resume for this row yet.
              </p>
              <p className="max-w-sm text-xs text-slate-600">
                A tailored PDF appears here once the service generates one for{" "}
                {app.company || "this company"}.
              </p>
            </div>
            <PeoplePanel app={app} people={people} onAddPerson={onAddPerson} />
          </div>
        ) : phase === "loading" ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
            <span className="text-sm">Loading tailored resume…</span>
          </div>
        ) : phase === "error" ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 p-10 text-center">
            <AlertTriangle className="h-8 w-8 text-rose-400" aria-hidden />
            <p className="text-sm text-slate-300">{errorMsg}</p>
          </div>
        ) : (
          meta &&
          resolved && (
            <div className="flex flex-1 flex-col overflow-hidden">
              <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-2">
                {/* LEFT: JD + manifest */}
                <div className="overflow-y-auto border-b border-slate-800 p-4 lg:border-b-0 lg:border-r">
                  <section className="mb-5">
                    <div className="mb-2 rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-3">
                      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-indigo-300/80">
                        Summary
                      </div>
                      <p className="break-words text-sm text-slate-200">
                        {meta.manifest.summary || "—"}
                      </p>
                    </div>
                  </section>

                  <section className="mb-6">
                    <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200">
                      <Layers className="h-4 w-4 text-slate-400" aria-hidden />
                      Manifest — Bullets Selected
                    </h3>
                    <div className="space-y-3">
                      {resolved.jobs.map((g, i) => (
                        <ManifestGroup key={`job-${i}`} group={g} />
                      ))}
                      {resolved.projects.map((g, i) => (
                        <ManifestGroup key={`proj-${i}`} group={g} />
                      ))}
                      {resolved.achievements.length > 0 && (
                        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
                          <div className="text-sm font-medium text-slate-200">
                            Achievements
                          </div>
                          <ul className="mt-2 space-y-1.5">
                            {resolved.achievements.map((text, i) => (
                              <li
                                key={i}
                                className="flex gap-2 text-sm text-slate-300"
                              >
                                <span
                                  className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald-400"
                                  aria-hidden
                                />
                                <span className="break-words">{text}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {resolved.skills.length > 0 && (
                        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
                          <div className="text-sm font-medium text-slate-200">
                            Skills
                          </div>
                          <ul className="mt-2 space-y-1.5">
                            {resolved.skills.map((text) => (
                              <li
                                key={text}
                                className="border-l-2 border-cyan-800 pl-2 text-sm text-slate-300"
                              >
                                {text}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </section>

                  <section>
                    <h3 className="mb-2 text-sm font-semibold text-slate-200">
                      Job Description
                    </h3>
                    <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-slate-900/40 p-3 font-sans text-sm leading-relaxed text-slate-300">
                      {meta.jd_text || "—"}
                    </pre>
                  </section>
                </div>

                {/* RIGHT: PDF */}
                <div className="flex min-h-[40vh] flex-col overflow-hidden bg-slate-900/40 lg:min-h-0">
                  {id != null && (
                    <iframe
                      title="Tailored resume PDF"
                      src={`/api/tailored/${encodeURIComponent(id)}/pdf`}
                      className="h-full w-full flex-1 border-0 bg-white"
                    />
                  )}
                </div>
              </div>

              <PeoplePanel app={app} people={people} onAddPerson={onAddPerson} />
            </div>
          )
        )}
      </div>
    </div>
  );
}
