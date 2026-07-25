import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Download,
  FileOutput,
  Loader2,
  RefreshCw,
} from "lucide-react";
import type {
  JobWorkspace,
  ResumeBank,
  TailoredResumeMeta,
} from "../types";
import { fetchTailored, loadResumeBank } from "../api";

interface Props {
  job: JobWorkspace;
  busy: boolean;
  onTailor: () => Promise<void>;
}

interface SelectedGroup {
  title: string;
  subtitle: string;
  bullets: string[];
}

function resolveSelection(
  meta: TailoredResumeMeta,
  bank: ResumeBank
): SelectedGroup[] {
  const jobs = new Map(bank.jobs.map((job) => [job.id, job]));
  const projects = new Map(bank.projects.map((project) => [project.id, project]));
  const groups: SelectedGroup[] = [];

  for (const selection of meta.manifest.job_selections) {
    const job = jobs.get(selection.job_id);
    const bullets = new Map((job?.bullets ?? []).map((bullet) => [bullet.id, bullet.text]));
    groups.push({
      title: job?.title ?? selection.job_id,
      subtitle: job?.company ?? "Experience",
      bullets: selection.bullet_ids.map(
        (id) => bullets.get(id) ?? `[missing source: ${id}]`
      ),
    });
  }
  for (const selection of meta.manifest.project_selections) {
    const project = projects.get(selection.project_id);
    const bullets = new Map(
      (project?.bullets ?? []).map((bullet) => [bullet.id, bullet.text])
    );
    groups.push({
      title: project?.name ?? selection.project_id,
      subtitle: "Project",
      bullets: selection.bullet_ids.map(
        (id) => bullets.get(id) ?? `[missing source: ${id}]`
      ),
    });
  }
  if (meta.manifest.achievement_ids.length > 0) {
    const achievements = new Map(
      bank.achievements.map((achievement) => [achievement.id, achievement.text])
    );
    groups.push({
      title: "Achievements",
      subtitle: "",
      bullets: meta.manifest.achievement_ids.map(
        (id) => achievements.get(id) ?? `[missing source: ${id}]`
      ),
    });
  }
  const skillById = new Map(bank.skills.map((skill) => [skill.id, skill]));
  const skillIds =
    meta.manifest.skill_ids.length > 0
      ? meta.manifest.skill_ids
      : bank.skills.map((skill) => skill.id);
  if (skillIds.length > 0) {
    groups.push({
      title: "Skills",
      subtitle: "Selected categories",
      bullets: skillIds.map((id) => {
        const skill = skillById.get(id);
        return skill ? `${skill.category}: ${skill.items}` : `[missing source: ${id}]`;
      }),
    });
  }
  return groups;
}

export default function JobResume({ job, busy, onTailor }: Props) {
  const id = job.tailored_resume_id;
  const [meta, setMeta] = useState<TailoredResumeMeta | null>(null);
  const [bank, setBank] = useState<ResumeBank | null>(null);
  const [loading, setLoading] = useState(Boolean(id));
  const [error, setError] = useState("");

  useEffect(() => {
    if (!id) {
      setMeta(null);
      setBank(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([fetchTailored(id), loadResumeBank()])
      .then(([nextMeta, nextBank]) => {
        if (cancelled) return;
        setMeta(nextMeta);
        setBank(nextBank);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load resume.");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const groups = useMemo(
    () => (meta && bank ? resolveSelection(meta, bank) : []),
    [meta, bank]
  );

  if (!id) {
    return (
      <div className="flex min-h-[32rem] flex-col items-center justify-center gap-4 px-6 text-center">
        <FileOutput className="h-9 w-9 text-zinc-700" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-300">No tailored resume</h3>
          <p className="mt-1 text-xs text-zinc-600">
            {job.jd_text.trim()
              ? "Generate from the saved job description."
              : "Save the full job description first."}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onTailor()}
          disabled={busy || job.jd_text.trim().length < 80}
          className="inline-flex items-center gap-2 rounded-md bg-teal-600 px-3 py-2 text-sm font-medium text-white hover:bg-teal-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FileOutput className="h-4 w-4" />
          )}
          {busy ? "Tailoring..." : "Tailor resume"}
        </button>
      </div>
    );
  }

  return (
    <div className="grid min-h-[calc(100vh-14rem)] grid-cols-1 lg:grid-cols-[minmax(0,0.9fr)_minmax(480px,1.1fr)]">
      <div className="overflow-y-auto border-b border-zinc-800 lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-3">
          <span className="text-xs text-zinc-500">
            {meta ? `${meta.pages} page${meta.pages === 1 ? "" : "s"}` : "Artifact"}
          </span>
          <a
            href={`/api/tailored/${encodeURIComponent(id)}/pdf`}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100"
            aria-label="Open tailored resume PDF"
            title="Open PDF"
          >
            <Download className="h-4 w-4" />
          </a>
          <button
            type="button"
            onClick={() => void onTailor()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Regenerate
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-24 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading artifact...
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 p-5 text-sm text-rose-400">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        ) : (
          meta && (
            <div className="divide-y divide-zinc-800">
              <section className="px-4 py-5">
                <h3 className="text-xs font-semibold uppercase text-zinc-500">
                  Tailored summary
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-zinc-300">
                  {meta.manifest.summary}
                </p>
              </section>
              <section className="px-4 py-5">
                <h3 className="text-xs font-semibold uppercase text-zinc-500">
                  Selected evidence
                </h3>
                <div className="mt-3 divide-y divide-zinc-800 border-y border-zinc-800">
                  {groups.map((group, index) => (
                    <div key={`${group.title}-${index}`} className="py-4">
                      <div className="text-sm font-medium text-zinc-200">
                        {group.title}
                      </div>
                      {group.subtitle && (
                        <div className="text-xs text-zinc-600">{group.subtitle}</div>
                      )}
                      <ul className="mt-2 space-y-2">
                        {group.bullets.map((bullet, bulletIndex) => (
                          <li
                            key={bulletIndex}
                            className="border-l-2 border-teal-900 pl-2 text-xs leading-relaxed text-zinc-400"
                          >
                            {bullet}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          )
        )}
      </div>
      <div className="min-h-[42rem] bg-white">
        <iframe
          key={id}
          title={`Tailored resume for ${job.company}`}
          src={`/api/tailored/${encodeURIComponent(id)}/pdf`}
          className="h-full min-h-[42rem] w-full border-0"
        />
      </div>
    </div>
  );
}
