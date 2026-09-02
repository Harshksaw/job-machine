import { Check, Copy, Loader2, Sparkles } from "lucide-react";
import { useState } from "react";
import type { JobWorkspaceInput } from "../types";

interface Props {
  draft: JobWorkspaceInput;
  busy: boolean;
  onChange: (value: string) => void;
  onGenerate: () => Promise<void>;
}

export default function JobLetter({
  draft,
  busy,
  onChange,
  onGenerate,
}: Props) {
  const [copied, setCopied] = useState(false);
  const words = draft.cover_letter.trim()
    ? draft.cover_letter.trim().split(/\s+/).length
    : 0;

  const copy = async () => {
    await navigator.clipboard.writeText(draft.cover_letter);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className="divide-y divide-zinc-800">
      {draft.fit_analysis?.role_thesis && (
        <section className="px-4 py-4 lg:px-6">
          <div className="jm-section-title">
            Positioning thesis
          </div>
          <p className="mt-1 text-base leading-7 text-zinc-200">
            {draft.fit_analysis.role_thesis}
          </p>
        </section>
      )}

      <section className="px-4 py-5 lg:px-6">
        <div className="mb-2 flex items-center gap-2">
          <label
            htmlFor="cover-letter"
            className="text-sm font-semibold text-zinc-200"
          >
            Cover letter
          </label>
          <span className="text-xs text-zinc-600">{words} words</span>
          <button
            type="button"
            onClick={() => void copy()}
            disabled={!draft.cover_letter}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-30"
          >
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            onClick={() => void onGenerate()}
            disabled={busy || draft.jd_text.trim().length < 80}
            className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-40"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {draft.cover_letter ? "Regenerate kit" : "Generate kit"}
          </button>
        </div>
        <textarea
          id="cover-letter"
          className="jm-input min-h-[34rem] w-full resize-y px-4 py-4 text-base leading-7"
          value={draft.cover_letter}
          onChange={(event) => onChange(event.target.value)}
          placeholder="No cover letter generated."
        />
      </section>

      {draft.fit_analysis && draft.fit_analysis.evidence.length > 0 && (
        <section className="px-4 py-5 lg:px-6">
          <h3 className="text-xs font-semibold uppercase text-zinc-500">
            Claim ledger
          </h3>
          <div className="mt-3 divide-y divide-zinc-800 border-y border-zinc-800">
            {draft.fit_analysis.evidence
              .filter((item) => item.source_ids.length > 0)
              .map((item, index) => (
                <div key={`${item.requirement}-${index}`} className="py-3">
                  <div className="text-sm text-zinc-300">{item.proof}</div>
                  <div className="mt-1 font-mono text-[11px] text-zinc-600">
                    {item.source_ids.join(", ")}
                  </div>
                </div>
              ))}
          </div>
        </section>
      )}
    </div>
  );
}
