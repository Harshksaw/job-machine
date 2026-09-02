import { useState } from "react";
import { Send, X, Plus, Trash2 } from "lucide-react";
import type { Person, PersonInput, Link } from "../types";
import { PERSON_STATUSES, STATUS_LABEL } from "../lib/people";

interface Props {
  initial?: Person | null;
  companies: string[];
  defaultCompany?: string;
  defaultRole?: string;
  defaultJobId?: string;
  onCancel: () => void;
  onSave: (body: PersonInput) => Promise<void>;
}

const EMPTY: PersonInput = {
  name: "", title: "", company: "", role: null, job_id: "", linkedin_url: "",
  links: [], status: "to-reach", hook: "", message: "", notes: "",
};

export default function PersonForm({ initial, companies, defaultCompany, defaultRole, defaultJobId, onCancel, onSave }: Props) {
  const [form, setForm] = useState<PersonInput>(() =>
    initial
      ? { ...initial }
      : { ...EMPTY, company: defaultCompany ?? "", role: defaultRole ?? null, job_id: defaultJobId ?? "" }
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const isQueuedReview = initial?.status === "queued" || form.status === "queued";

  const set = <K extends keyof PersonInput>(k: K, v: PersonInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const setLink = (i: number, patch: Partial<Link>) =>
    setForm((f) => ({ ...f, links: f.links.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const addLink = () => setForm((f) => ({ ...f, links: [...f.links, { label: "", url: "" }] }));
  const removeLink = (i: number) => setForm((f) => ({ ...f, links: f.links.filter((_, j) => j !== i) }));

  const persist = async (status?: string) => {
    setErr("");
    if (!form.name.trim() || !form.company.trim()) {
      setErr("Name and company are required.");
      return;
    }
    setSaving(true);
    try {
      await onSave({
        ...form,
        role: form.role?.trim() ? form.role : null,
        status: status ?? form.status,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save.");
      setSaving(false);
    }
  };

  const field = "jm-input";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" onClick={onCancel}>
      <div className={`flex max-h-[90vh] w-full flex-col overflow-hidden rounded-lg border border-zinc-700 bg-canvas shadow-2xl ${
          isQueuedReview ? "max-w-2xl" : "max-w-lg"
        }`}
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="person-form-title">
        <header className="flex items-center justify-between border-b border-zinc-700 px-4 py-3">
          <div>
            <h2 id="person-form-title" className="text-base font-semibold text-zinc-100">
              {isQueuedReview ? "Review outreach" : initial ? "Edit person" : "Add person"}
            </h2>
            {isQueuedReview && (
              <p className="mt-0.5 text-sm text-zinc-400">
                Edit the message if needed, then approve for the agent to send on LinkedIn.
              </p>
            )}
          </div>
          <button type="button" onClick={onCancel} className="rounded-md p-1 text-zinc-300 hover:bg-raised" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-3 overflow-y-auto p-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm text-zinc-300">Name*
              <input className={field} value={form.name} onChange={(e) => set("name", e.target.value)} />
            </label>
            <label className="text-sm text-zinc-300">Title
              <input className={field} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Engineering Manager" />
            </label>
            <label className="text-sm text-zinc-300">Company*
              <input className={field} list="known-companies" value={form.company} onChange={(e) => set("company", e.target.value)} />
              <datalist id="known-companies">{companies.map((c) => <option key={c} value={c} />)}</datalist>
            </label>
            <label className="text-sm text-zinc-300">Role (optional tie)
              <input className={field} value={form.role ?? ""} onChange={(e) => set("role", e.target.value)} placeholder="Backend Engineer" />
            </label>
          </div>
          <label className="block text-sm text-zinc-300">LinkedIn URL
            <input className={field} value={form.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} placeholder="https://linkedin.com/in/…" />
          </label>
          <div>
            <div className="mb-1 flex items-center justify-between text-sm text-zinc-300">
              <span>Extra links</span>
              <button type="button" onClick={addLink} className="inline-flex items-center gap-1 text-teal-200 hover:text-teal-100">
                <Plus className="h-3.5 w-3.5" /> Add link
              </button>
            </div>
            <div className="space-y-2">
              {form.links.map((l, i) => (
                <div key={i} className="flex gap-2">
                  <input className={field + " w-1/3"} value={l.label} onChange={(e) => setLink(i, { label: e.target.value })} placeholder="GitHub" />
                  <input className={field} value={l.url} onChange={(e) => setLink(i, { url: e.target.value })} placeholder="https://…" />
                  <button type="button" onClick={() => removeLink(i)} className="rounded-md p-1.5 text-slate-500 hover:text-rose-300" aria-label="Remove link">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
          {!isQueuedReview && (
            <div className="grid grid-cols-2 gap-3">
              <label className="text-sm text-zinc-300">Status
                <select className={field} value={form.status} onChange={(e) => set("status", e.target.value)}>
                  {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                </select>
              </label>
              <label className="text-sm text-zinc-300">Hook
                <input className={field} value={form.hook} onChange={(e) => set("hook", e.target.value)} placeholder="angle for outreach" />
              </label>
            </div>
          )}
          {isQueuedReview && form.hook && (
            <p className="rounded-md border border-zinc-700 bg-raised px-3 py-2 text-sm text-zinc-300">
              <span className="font-medium text-zinc-200">Hook: </span>
              {form.hook}
            </p>
          )}
          <label className="block text-sm text-zinc-300">Message
            <textarea className={`${field} ${isQueuedReview ? "min-h-[9rem] text-base leading-relaxed" : "min-h-[64px]"}`} value={form.message} onChange={(e) => set("message", e.target.value)} placeholder="drafted / sent outreach text" />
          </label>
          <label className="block text-sm text-zinc-300">Notes
            <textarea className={field + " min-h-[48px]"} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </label>
          {err && <p className="text-sm text-rose-400">{err}</p>}
        </div>
        <footer className="flex flex-wrap justify-end gap-2 border-t border-zinc-700 px-4 py-3">
          <button type="button" onClick={onCancel} className="jm-btn-secondary">Cancel</button>
          {isQueuedReview ? (
            <>
              <button type="button" onClick={() => void persist("skip")} disabled={saving} className="jm-btn-secondary">
                <X className="h-4 w-4" aria-hidden />
                Skip
              </button>
              <button type="button" onClick={() => void persist("queued")} disabled={saving} className="jm-btn-secondary">
                {saving ? "Saving…" : "Save draft"}
              </button>
              <button type="button" onClick={() => void persist("approved")} disabled={saving} className="jm-btn-primary">
                {saving ? "Saving…" : (<><Send className="h-4 w-4" aria-hidden />Approve & Send</>)}
              </button>
            </>
          ) : (
            <button type="button" onClick={() => void persist()} disabled={saving} className="jm-btn-primary">
              {saving ? "Saving…" : "Save"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
