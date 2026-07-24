import { useMemo, useState } from "react";
import { Plus, Pencil, Trash2, ExternalLink, Linkedin, Search } from "lucide-react";
import type { Person, PersonInput } from "../types";
import { createPerson, updatePerson, deletePerson } from "../api";
import { PERSON_STATUSES, STATUS_LABEL, STATUS_STYLE, statusRank, safeHref } from "../lib/people";
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

  const chip = "inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-xs text-slate-300 hover:border-indigo-500/40 hover:text-indigo-300";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search people…"
            className="w-56 rounded-lg border border-slate-800 bg-slate-900 py-1.5 pl-7 pr-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-sm text-slate-300">
          <option value="all">All statuses</option>
          {PERSON_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
        </select>
        <span className="text-xs text-slate-500">{shown.length} of {people.length}</span>
        <button type="button" onClick={() => setAdding(true)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500">
          <Plus className="h-3.5 w-3.5" /> Add person
        </button>
      </div>

      {shown.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-10 text-center text-sm text-slate-500">
          No people yet. Click “Add person” to start your outreach list.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900/60 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Name</th><th className="px-3 py-2">Company</th>
                <th className="px-3 py-2">Status</th><th className="px-3 py-2">Links</th>
                <th className="px-3 py-2">Hook</th><th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {shown.map((p) => (
                <tr key={p.id} className="hover:bg-slate-900/40">
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-100">{p.name}</div>
                    <div className="text-xs text-slate-500">{p.title}</div>
                  </td>
                  <td className="px-3 py-2 text-slate-300">
                    {p.company}{p.role ? <span className="text-slate-500"> · {p.role}</span> : null}
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
                  <td className="px-3 py-2 max-w-[16rem] truncate text-slate-400" title={p.hook}>{p.hook}</td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button type="button" onClick={() => setEditing(p)} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-slate-100" aria-label="Edit"><Pencil className="h-4 w-4" /></button>
                      <button type="button" onClick={() => remove(p)} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-rose-300" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>
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
