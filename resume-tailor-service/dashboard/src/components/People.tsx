import { useMemo, useState } from "react";
import { Plus, Pencil, Trash2, ExternalLink, Linkedin, Search, Check, Send, X } from "lucide-react";
import type { Person, PersonInput } from "../types";
import { createPerson, updatePerson, deletePerson } from "../api";
import { PERSON_STATUSES, STATUS_LABEL, STATUS_STYLE, statusRank, safeHref, toPersonInput } from "../lib/people";
import PersonForm from "./PersonForm";

interface Props {
  people: Person[];
  companies: string[];
  onChanged: () => void;
}

export default function People({ people, companies, onChanged }: Props) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [editing, setEditing] = useState<Person | null>(null);
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const queuedCount = useMemo(() => people.filter((p) => p.status === "queued").length, [people]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people
      .filter((p) => status === "all" || p.status === status)
      .filter((p) =>
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.company.toLowerCase().includes(q) ||
        p.title.toLowerCase().includes(q)
      )
      .sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.company.localeCompare(b.company));
  }, [people, query, status]);

  const save = async (body: PersonInput) => {
    if (editing) await updatePerson(editing.id, body);
    else await createPerson(body);
    setEditing(null);
    setAdding(false);
    onChanged();
  };

  const remove = async (p: Person) => {
    await deletePerson(p.id);
    onChanged();
  };

  const setPersonStatus = async (person: Person, nextStatus: string) => {
    setBusyId(person.id);
    try {
      await updatePerson(person.id, { ...toPersonInput(person), status: nextStatus });
      onChanged();
    } finally {
      setBusyId(null);
    }
  };

  const chip = "inline-flex items-center gap-1 rounded-md border border-zinc-600 bg-surface px-1.5 py-0.5 text-xs text-zinc-200 hover:border-teal-500/40 hover:text-teal-200";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <label htmlFor="people-search" className="visually-hidden">Search people</label>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" aria-hidden />
          <input id="people-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search people…"
            className="jm-input w-56 pl-8" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="jm-input w-auto" aria-label="Filter by status">
          <option value="all">All statuses</option>
          {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        {queuedCount > 0 && (
          <button
            type="button"
            onClick={() => setStatus(status === "queued" ? "all" : "queued")}
            aria-pressed={status === "queued"}
            className={`jm-btn-secondary ${status === "queued" ? "border-sky-600 bg-sky-950/40 text-sky-100" : ""}`}
          >
            <Send className="h-3.5 w-3.5" aria-hidden />
            {queuedCount} to approve
          </button>
        )}
        <span className="text-sm text-zinc-400">{shown.length} of {people.length}</span>
        <button type="button" onClick={() => setAdding(true)}
          className="jm-btn-primary ml-auto">
          <Plus className="h-3.5 w-3.5" /> Add person
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="rounded-lg border border-zinc-700 bg-surface p-10 text-center text-sm text-zinc-400">
          No people yet. Click “Add person” to start your outreach list.
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-zinc-700">
          <table className="w-full text-sm">
            <thead className="bg-surface text-left text-xs uppercase tracking-wide text-zinc-400">
              <tr>
                <th className="px-3 py-2">Name</th><th className="px-3 py-2">Company</th>
                <th className="px-3 py-2">Status</th><th className="px-3 py-2">Links</th>
                <th className="px-3 py-2">Hook</th><th className="px-3 py-2">Message</th><th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {shown.map((p) => (
                <tr key={p.id} className="hover:bg-raised">
                  <td className="px-3 py-3">
                    <div className="font-medium text-zinc-100">{p.name}</div>
                    <div className="text-sm text-zinc-400">{p.title}</div>
                  </td>
                  <td className="px-3 py-3 text-zinc-200">
                    {p.company}{p.role ? <span className="text-zinc-400"> · {p.role}</span> : null}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-xs ${STATUS_STYLE[p.status] ?? ""}`}>
                      {STATUS_LABEL[p.status] ?? p.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {safeHref(p.linkedin_url) && (
                        <a className={chip} href={safeHref(p.linkedin_url)!} target="_blank" rel="noopener noreferrer">
                          <Linkedin className="h-3 w-3" /> LinkedIn
                        </a>
                      )}
                      {p.links.map((l, i) => safeHref(l.url) && (
                        <a key={i} className={chip} href={safeHref(l.url)!} target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-3 w-3" /> {l.label || "link"}
                        </a>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-3 max-w-[16rem] truncate text-zinc-300" title={p.hook}>{p.hook}</td>
                  <td className="px-3 py-3 max-w-[20rem]">
                    {p.message ? (
                      <button
                        type="button"
                        onClick={() => setEditing(p)}
                        className="line-clamp-2 text-left text-sm leading-relaxed text-zinc-300 hover:text-teal-200"
                        title={p.message}
                      >
                        {p.message}
                      </button>
                    ) : (
                      <span className="text-sm text-zinc-500">No draft</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap justify-end gap-1">
                      {p.status === "queued" && (
                        <>
                          <button
                            type="button"
                            disabled={busyId === p.id}
                            onClick={() => void setPersonStatus(p, "approved")}
                            className="jm-btn-primary h-8 px-2 text-xs"
                            aria-label={`Approve outreach to ${p.name}`}
                          >
                            <Check className="h-3.5 w-3.5" aria-hidden />
                            Approve
                          </button>
                          <button
                            type="button"
                            disabled={busyId === p.id}
                            onClick={() => setEditing(p)}
                            className="jm-btn-secondary h-8 px-2 text-xs"
                          >
                            Review
                          </button>
                          <button
                            type="button"
                            disabled={busyId === p.id}
                            onClick={() => void setPersonStatus(p, "skip")}
                            className="jm-btn-secondary h-8 px-2 text-xs"
                            aria-label={`Skip outreach to ${p.name}`}
                          >
                            <X className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </>
                      )}
                      <button type="button" onClick={() => setEditing(p)} className="rounded-md p-1.5 text-zinc-300 hover:bg-raised hover:text-zinc-100" aria-label={`Edit ${p.name}`}><Pencil className="h-4 w-4" aria-hidden /></button>
                      <button type="button" onClick={() => remove(p)} className="rounded-md p-1.5 text-zinc-300 hover:bg-raised hover:text-rose-300" aria-label={`Delete ${p.name}`}><Trash2 className="h-4 w-4" aria-hidden /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(adding || editing) && (
        <PersonForm
          initial={editing}
          companies={companies}
          onCancel={() => { setAdding(false); setEditing(null); }}
          onSave={save}
        />
      )}
    </div>
  );
}
