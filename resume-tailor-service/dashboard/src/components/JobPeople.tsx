import { useCallback, useEffect, useState } from "react";
import { Check, ExternalLink, Linkedin, Plus, UserRound, X } from "lucide-react";
import type { Person, PersonInput } from "../types";
import { addJobPerson, listJobPeople, updatePerson } from "../api";
import {
  PERSON_STATUSES,
  STATUS_LABEL,
  STATUS_STYLE,
  preserveJobAssociation,
  safeHref,
} from "../lib/people";
import PersonForm from "./PersonForm";

interface Props {
  jobId: string;
  company: string;
  role: string;
  onChanged?: () => void;
}

export default function JobPeople({ jobId, company, role, onChanged }: Props) {
  const [people, setPeople] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPeople(await listJobPeople(jobId));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load people.");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const save = async (body: PersonInput) => {
    if (editing) {
      await updatePerson(editing.id, preserveJobAssociation(body, editing));
    } else {
      await addJobPerson(jobId, {
        ...body,
        company: body.company.trim() || company,
        role: body.role || role,
        job_id: jobId,
      });
    }
    setAdding(false);
    setEditing(null);
    await load();
    onChanged?.();
  };

  const setStatus = async (person: Person, status: string) => {
    setBusyId(person.id);
    setError("");
    try {
      await updatePerson(
        person.id,
        preserveJobAssociation({ ...person, status }, person),
      );
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
          <UserRound className="h-4 w-4" aria-hidden />
          Reach out
        </h3>
        <span className="text-sm tabular-nums text-zinc-400">
          {people.length} on this job
        </span>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setAdding(true);
          }}
          className="jm-btn-secondary ml-auto h-9"
        >
          <Plus className="h-4 w-4" aria-hidden />
          Add someone
        </button>
      </div>
      <p className="mt-1 text-sm text-zinc-400">
        Contacts are saved on this listing. Outreach stays with the job after refresh.
      </p>

      {error && <p className="mt-2 text-sm text-rose-400">{error}</p>}

      {loading ? (
        <p className="mt-3 text-sm text-zinc-600">Loading people…</p>
      ) : people.length === 0 ? (
        <p className="mt-3 rounded-md border border-dashed border-zinc-600 px-3 py-4 text-sm text-zinc-400">
          No one on this ticket yet. Add a recruiter or engineer so reach-out is part of the apply.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-zinc-800 border-y border-zinc-700">
          {people.map((person) => {
            const linkedin = safeHref(person.linkedin_url);
            return (
              <li key={person.id} className="py-4">
                <div className="flex flex-wrap items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <button
                      type="button"
                      onClick={() => {
                        setAdding(false);
                        setEditing(person);
                      }}
                      className="text-left text-base font-medium text-zinc-100 hover:text-teal-200"
                    >
                      {person.name}
                    </button>
                    {person.title && (
                      <div className="text-sm text-zinc-300">{person.title}</div>
                    )}
                  </div>
                  {person.status === "queued" && (
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <button
                        type="button"
                        disabled={busyId === person.id}
                        onClick={() => void setStatus(person, "approved")}
                        aria-label={`Approve to send outreach to ${person.name}`}
                        className="jm-btn-primary h-9"
                      >
                        <Check className="h-4 w-4" aria-hidden />
                        Approve to send
                      </button>
                      <button
                        type="button"
                        disabled={busyId === person.id}
                        onClick={() => void setStatus(person, "skip")}
                        aria-label={`Skip outreach to ${person.name}`}
                        className="jm-btn-secondary h-9"
                      >
                        <X className="h-4 w-4" aria-hidden />
                        Skip
                      </button>
                    </div>
                  )}
                  <select
                    value={person.status}
                    disabled={busyId === person.id}
                    onChange={(event) => void setStatus(person, event.target.value)}
                    className={`rounded-md border px-2 py-1.5 text-sm ${
                      STATUS_STYLE[person.status] ?? "border-zinc-600 text-zinc-200"
                    } bg-transparent`}
                    aria-label={`Outreach status for ${person.name}`}
                  >
                    {PERSON_STATUSES.map((status) => (
                      <option key={status} value={status} className="bg-zinc-950 text-zinc-100">
                        {STATUS_LABEL[status]}
                      </option>
                    ))}
                  </select>
                  {linkedin && (
                    <a
                      href={linkedin}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-md p-2 text-zinc-300 hover:bg-raised hover:text-cyan-200"
                      aria-label={`Open ${person.name} on LinkedIn`}
                    >
                      <Linkedin className="h-4 w-4" aria-hidden />
                    </a>
                  )}
                  {person.links.map(
                    (link, index) =>
                      safeHref(link.url) && (
                        <a
                          key={`${link.url}-${index}`}
                          href={safeHref(link.url)!}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-md p-2 text-zinc-300 hover:bg-raised hover:text-cyan-200"
                          aria-label={link.label || "Open link"}
                        >
                          <ExternalLink className="h-4 w-4" aria-hidden />
                        </a>
                      )
                  )}
                </div>
                {person.hook && (
                  <p className="mt-2 text-sm text-zinc-300">{person.hook}</p>
                )}
                {person.message && (
                  <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">
                    {person.message}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {(adding || editing) && (
        <PersonForm
          initial={editing}
          companies={[company]}
          defaultCompany={company}
          defaultRole={role}
          defaultJobId={jobId}
          onCancel={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSave={save}
        />
      )}
    </section>
  );
}
