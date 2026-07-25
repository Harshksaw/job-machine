import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import type {
  ApplicationAnswer,
  ApplicationAnswerInput,
  JobWorkspace,
} from "../types";
import {
  addApplicationAnswer,
  deleteApplicationAnswer,
  generateApplicationAnswer,
  getJob,
  updateApplicationAnswer,
} from "../api";

interface Props {
  job: JobWorkspace;
  onUpdated: (job: JobWorkspace) => void;
}

const field =
  "w-full rounded-md border border-zinc-700 bg-zinc-950 px-2.5 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500/30";

function toInput(answer: ApplicationAnswer): ApplicationAnswerInput {
  return {
    question: answer.question,
    answer: answer.answer,
    constraints: answer.constraints,
    status: answer.status,
    source_ids: answer.source_ids,
    needs_user_input: answer.needs_user_input,
    clarification: answer.clarification,
  };
}

function AnswerRow({
  jobId,
  answer,
  onUpdated,
}: {
  jobId: string;
  answer: ApplicationAnswer;
  onUpdated: (job: JobWorkspace) => void;
}) {
  const [draft, setDraft] = useState<ApplicationAnswerInput>(() => toInput(answer));
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setDraft(toInput(answer)), [answer]);

  const set = <K extends keyof ApplicationAnswerInput>(
    key: K,
    value: ApplicationAnswerInput[K]
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      onUpdated(
        await updateApplicationAnswer(
          jobId,
          answer.id,
          draft,
          "Application form"
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save answer.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete this application answer?")) return;
    setSaving(true);
    try {
      await deleteApplicationAnswer(jobId, answer.id, "Application form");
      onUpdated(await getJob(jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete answer.");
      setSaving(false);
    }
  };

  const copy = async () => {
    await navigator.clipboard.writeText(draft.answer);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <article className="space-y-3 py-5">
      {draft.needs_user_input && (
        <div className="flex gap-2 rounded-md border border-amber-800/70 bg-amber-950/30 p-3 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{draft.clarification}</span>
        </div>
      )}
      <label className="block text-xs font-medium text-zinc-500">
        Question
        <textarea
          className={`${field} mt-1 min-h-20 resize-y`}
          value={draft.question}
          onChange={(event) => set("question", event.target.value)}
        />
      </label>
      <label className="block text-xs font-medium text-zinc-500">
        Answer
        <textarea
          className={`${field} mt-1 min-h-40 resize-y leading-relaxed`}
          value={draft.answer}
          onChange={(event) => {
            set("answer", event.target.value);
            if (draft.needs_user_input && event.target.value.trim()) {
              set("needs_user_input", false);
              set("clarification", "");
            }
          }}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <label className="block text-xs font-medium text-zinc-500">
          Constraints
          <input
            className={`${field} mt-1`}
            value={draft.constraints}
            onChange={(event) => set("constraints", event.target.value)}
          />
        </label>
        <label className="block text-xs font-medium text-zinc-500">
          Status
          <select
            className={`${field} mt-1`}
            value={draft.status}
            onChange={(event) =>
              set("status", event.target.value as ApplicationAnswerInput["status"])
            }
          >
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="submitted">Submitted</option>
          </select>
        </label>
      </div>
      {draft.source_ids.length > 0 && (
        <p className="font-mono text-[11px] text-zinc-600">
          {draft.source_ids.join(", ")}
        </p>
      )}
      {error && <p className="text-sm text-rose-400">{error}</p>}
      <div className="flex justify-end gap-1.5">
        <button
          type="button"
          onClick={() => void copy()}
          disabled={!draft.answer}
          className="rounded-md p-2 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-100 disabled:opacity-30"
          aria-label="Copy answer"
          title="Copy answer"
        >
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
        </button>
        <button
          type="button"
          onClick={() => void remove()}
          disabled={saving}
          className="rounded-md p-2 text-zinc-500 hover:bg-zinc-800 hover:text-rose-300"
          aria-label="Delete answer"
          title="Delete answer"
        >
          <Trash2 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !draft.question.trim()}
          className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-2 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          Save
        </button>
      </div>
    </article>
  );
}

export default function JobAnswers({ job, onUpdated }: Props) {
  const [question, setQuestion] = useState("");
  const [constraints, setConstraints] = useState("");
  const [busy, setBusy] = useState<"draft" | "blank" | null>(null);
  const [error, setError] = useState("");

  const create = async (generated: boolean) => {
    if (!question.trim()) return;
    setBusy(generated ? "draft" : "blank");
    setError("");
    try {
      const updated = generated
        ? await generateApplicationAnswer(
            job.id,
            question,
            constraints,
            "Application form"
          )
        : await addApplicationAnswer(
            job.id,
            {
              question,
              answer: "",
              constraints,
              status: "draft",
              source_ids: [],
              needs_user_input: false,
              clarification: "",
            },
            "Application form"
          );
      setQuestion("");
      setConstraints("");
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add answer.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="px-4 py-5 lg:px-6">
      <section className="border-b border-zinc-800 pb-5">
        <label className="block text-xs font-medium text-zinc-500">
          Application question
          <textarea
            className={`${field} mt-1 min-h-24 resize-y`}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
        <label className="mt-3 block text-xs font-medium text-zinc-500">
          Form constraints
          <input
            className={`${field} mt-1`}
            value={constraints}
            onChange={(event) => setConstraints(event.target.value)}
            placeholder="150 words, technical audience"
          />
        </label>
        {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => void create(false)}
            disabled={busy !== null || !question.trim()}
            className="inline-flex items-center gap-1.5 rounded-md border border-zinc-700 px-3 py-2 text-xs text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
          >
            {busy === "blank" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Add blank
          </button>
          <button
            type="button"
            onClick={() => void create(true)}
            disabled={busy !== null || !question.trim()}
            className="inline-flex items-center gap-1.5 rounded-md bg-teal-600 px-3 py-2 text-xs font-medium text-white hover:bg-teal-500 disabled:opacity-40"
          >
            {busy === "draft" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Draft answer
          </button>
        </div>
      </section>

      {job.application_answers.length === 0 ? (
        <div className="py-20 text-center text-sm text-zinc-600">
          No application questions saved.
        </div>
      ) : (
        <div className="divide-y divide-zinc-800">
          {job.application_answers.map((answer) => (
            <AnswerRow
              key={answer.id}
              jobId={job.id}
              answer={answer}
              onUpdated={onUpdated}
            />
          ))}
        </div>
      )}
    </div>
  );
}
