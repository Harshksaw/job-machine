import { useState } from "react";
import { X, Plus, Trash2 } from "lucide-react";
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

  const set = <K extends keyof PersonInput>(k: K, v: PersonInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const setLink = (i: number, patch: Partial<Link>) =>
    setForm((f) => ({ ...f, links: f.links.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const addLink = () => setForm((f) => ({ ...f, links: [...f.links, { label: "", url: "" }] }));
  const removeLink = (i: number) => setForm((f) => ({ ...f, links: f.links.filter((_, j) => j !== i) }));

  const submit = async () => {
    setErr("");
    if (!form.name.trim() || !form.company.trim()) {
      setErr("Name and company are required.");
      return;
    }
    setSaving(true);
    try {
      await onSave({ ...form, role: form.role?.trim() ? form.role : null });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save.");
      setSaving(false);
    }
  };

  const field = "w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" onClick={onCancel}>
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">{initial ? "Edit person" : "Add person"}</h2>
          <button type="button" onClick={onCancel} className="rounded-md p-1 text-slate-400 hover:bg-slate-800" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="space-y-3 overflow-y-auto p-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Name*
              <input className={field} value={form.name} onChange={(e) => set("name", e.target.value)} />
            </label>
            <label className="text-xs text-slate-400">Title
              <input className={field} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="Engineering Manager" />
            </label>
            <label className="text-xs text-slate-400">Company*
              <input className={field} list="known-companies" value={form.company} onChange={(e) => set("company", e.target.value)} />
              <datalist id="known-companies">{companies.map((c) => <option key={c} value={c} />)}</datalist>
            </label>
            <label className="text-xs text-slate-400">Role (optional tie)
              <input className={field} value={form.role ?? ""} onChange={(e) => set("role", e.target.value)} placeholder="Backend Engineer" />
            </label>
          </div>
          <label className="block text-xs text-slate-400">LinkedIn URL
            <input className={field} value={form.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} placeholder="https://linkedin.com/in/…" />
          </label>
          <div>
            <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
              <span>Extra links</span>
              <button type="button" onClick={addLink} className="inline-flex items-center gap-1 text-indigo-300 hover:text-indigo-200">
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
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-400">Status
              <select className={field} value={form.status} onChange={(e) => set("status", e.target.value)}>
                {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
              </select>
            </label>
            <label className="text-xs text-slate-400">Hook
              <input className={field} value={form.hook} onChange={(e) => set("hook", e.target.value)} placeholder="angle for outreach" />
            </label>
          </div>
          <label className="block text-xs text-slate-400">Message
            <textarea className={field + " min-h-[64px]"} value={form.message} onChange={(e) => set("message", e.target.value)} placeholder="drafted / sent outreach text" />
          </label>
          <label className="block text-xs text-slate-400">Notes
            <textarea className={field + " min-h-[48px]"} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
          </label>
          {err && <p className="text-sm text-rose-400">{err}</p>}
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-800 px-4 py-3">
          <button type="button" onClick={onCancel} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={submit} disabled={saving}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}
