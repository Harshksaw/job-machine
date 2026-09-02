import { Target } from "lucide-react";
import type { JobWorkspaceInput } from "../types";
import JobPeople from "./JobPeople";

interface Props {
  jobId: string;
  draft: JobWorkspaceInput;
  onChange: <K extends keyof JobWorkspaceInput>(
    key: K,
    value: JobWorkspaceInput[K]
  ) => void;
  onPeopleChanged?: () => void;
}

const field = "jm-input mt-1";
const label = "text-sm font-medium text-zinc-300";

export default function JobOverview({ jobId, draft, onChange, onPeopleChanged }: Props) {
  const analysis = draft.fit_analysis;

  return (
    <div className="divide-y divide-zinc-800">
      {analysis && (
        <section className="space-y-4 px-4 py-5 lg:px-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-teal-700/60 bg-teal-950/50 text-lg font-semibold text-teal-300">
              {analysis.score}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-zinc-100">Fit decision</h3>
                <span
                  className={`rounded-md border px-2 py-0.5 text-xs font-medium ${
                    analysis.recommendation === "apply"
                      ? "border-emerald-700/70 bg-emerald-950/50 text-emerald-300"
                      : "border-amber-700/70 bg-amber-950/40 text-amber-300"
                  }`}
                >
                  {analysis.recommendation === "apply" ? "Apply" : "Review"}
                </span>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-zinc-300">
                {analysis.verdict}
              </p>
              {analysis.role_thesis && (
                <p className="mt-2 flex gap-2 text-sm leading-relaxed text-zinc-400">
                  <Target className="mt-0.5 h-4 w-4 shrink-0 text-teal-400" />
                  {analysis.role_thesis}
                </p>
              )}
            </div>
          </div>

          {analysis.keywords.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {analysis.keywords.map((keyword) => (
                <span
                  key={keyword}
                  className="rounded-md border border-cyan-800/60 bg-cyan-950/30 px-2 py-1 text-xs text-cyan-300"
                >
                  {keyword}
                </span>
              ))}
            </div>
          )}

          {analysis.evidence.length > 0 && (
            <div className="overflow-x-auto rounded-md border border-zinc-800">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase text-zinc-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Requirement</th>
                    <th className="px-3 py-2 font-medium">Match</th>
                    <th className="px-3 py-2 font-medium">Verified proof</th>
                    <th className="px-3 py-2 font-medium">Sources</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {analysis.evidence.map((item, index) => (
                    <tr key={`${item.requirement}-${index}`}>
                      <td className="px-3 py-2.5 text-zinc-200">{item.requirement}</td>
                      <td className="px-3 py-2.5">
                        <span
                          className={`rounded-md border px-1.5 py-0.5 text-xs ${
                            item.strength === "strong"
                              ? "border-emerald-800 bg-emerald-950/40 text-emerald-300"
                              : item.strength === "partial"
                                ? "border-amber-800 bg-amber-950/40 text-amber-300"
                                : "border-rose-900 bg-rose-950/30 text-rose-300"
                          }`}
                        >
                          {item.strength}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 leading-relaxed text-zinc-400">
                        {item.proof || "No direct evidence"}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[11px] text-zinc-500">
                        {item.source_ids.join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {(analysis.gaps.length > 0 || analysis.positioning.length > 0) && (
            <div className="grid gap-5 md:grid-cols-2">
              <div>
                <h4 className="text-xs font-semibold uppercase text-zinc-500">Gaps</h4>
                <ul className="mt-2 space-y-1.5 text-sm text-zinc-400">
                  {analysis.gaps.map((gap) => (
                    <li key={gap} className="border-l-2 border-rose-900 pl-2">
                      {gap}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-xs font-semibold uppercase text-zinc-500">
                  Positioning
                </h4>
                <ul className="mt-2 space-y-1.5 text-sm text-zinc-400">
                  {analysis.positioning.map((item) => (
                    <li key={item} className="border-l-2 border-teal-800 pl-2">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="grid gap-4 px-4 py-5 sm:grid-cols-2 lg:px-6">
        <label className={label}>
          Job URL
          <input
            className={field}
            value={draft.job_url}
            onChange={(event) => onChange("job_url", event.target.value)}
          />
        </label>
        <label className={label}>
          Source
          <input
            className={field}
            value={draft.source}
            onChange={(event) => onChange("source", event.target.value)}
          />
        </label>
        <label className={label}>
          Location
          <input
            className={field}
            value={draft.location}
            onChange={(event) => onChange("location", event.target.value)}
          />
        </label>
        <label className={label}>
          Work mode
          <input
            className={field}
            value={draft.work_mode}
            onChange={(event) => onChange("work_mode", event.target.value)}
          />
        </label>
        <label className={label}>
          Compensation
          <input
            className={field}
            value={draft.compensation}
            onChange={(event) => onChange("compensation", event.target.value)}
          />
        </label>
        <label className={label}>
          Deadline
          <input
            className={field}
            type="date"
            value={draft.deadline}
            onChange={(event) => onChange("deadline", event.target.value)}
          />
        </label>
        <label className={`${label} sm:col-span-2`}>
          Next action
          <input
            className={field}
            value={draft.next_action}
            onChange={(event) => onChange("next_action", event.target.value)}
            placeholder="Submit application, find hiring manager, follow up"
          />
        </label>
      </section>

      <section className="grid gap-5 px-4 py-5 lg:grid-cols-2 lg:px-6">
        <label className={label}>
          Company context
          <textarea
            className={`${field} min-h-36 resize-y leading-relaxed`}
            value={draft.company_context}
            onChange={(event) => onChange("company_context", event.target.value)}
          />
        </label>
        <label className={label}>
          Why this role
          <textarea
            className={`${field} min-h-36 resize-y leading-relaxed`}
            value={draft.why_this_role}
            onChange={(event) => onChange("why_this_role", event.target.value)}
          />
        </label>
        <label className={`${label} lg:col-span-2`}>
          Notes
          <textarea
            className={`${field} min-h-28 resize-y leading-relaxed`}
            value={draft.notes}
            onChange={(event) => onChange("notes", event.target.value)}
          />
        </label>
      </section>

      <section className="px-4 py-5 lg:px-6">
        <label className={label}>
          Full job description
          <textarea
            className={`${field} min-h-[28rem] resize-y whitespace-pre-wrap font-mono text-sm leading-relaxed`}
            value={draft.jd_text}
            onChange={(event) => onChange("jd_text", event.target.value)}
          />
        </label>
      </section>

      <section className="px-4 py-5 lg:px-6">
        <JobPeople
          jobId={jobId}
          company={draft.company}
          role={draft.role}
          onChanged={onPeopleChanged}
        />
      </section>
    </div>
  );
}
