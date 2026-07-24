// Same-origin API client. The service is local-only and unauthenticated, so
// requests are plain fetch with no Authorization header.

import type { Application, Person, PersonInput, ResumeBank, TailoredResumeMeta } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, init);
}

export async function fetchApplications(): Promise<Application[]> {
  const res = await apiFetch("/api/applications");
  if (!res.ok) {
    const msg =
      res.status === 502
        ? "Failed to load applications from the sheet."
        : `Failed to load applications (HTTP ${res.status}).`;
    throw new ApiError(msg, res.status);
  }
  return (await res.json()) as Application[];
}

export async function fetchTailored(id: string): Promise<TailoredResumeMeta> {
  const res = await apiFetch(`/api/tailored/${encodeURIComponent(id)}`);
  if (!res.ok) {
    const msg =
      res.status === 404
        ? "Tailored resume not found."
        : res.status === 400
          ? "Invalid tailored resume id."
          : `Failed to load tailored resume (HTTP ${res.status}).`;
    throw new ApiError(msg, res.status);
  }
  return (await res.json()) as TailoredResumeMeta;
}

// The resume bank rarely changes across a session, so cache the in-flight
// promise once. A failed fetch resets the cache so it can be retried.
let bankPromise: Promise<ResumeBank> | null = null;

export function loadResumeBank(): Promise<ResumeBank> {
  if (!bankPromise) {
    bankPromise = (async () => {
      const res = await apiFetch("/api/resume-bank");
      if (!res.ok) {
        throw new ApiError(`Failed to load resume bank (HTTP ${res.status}).`, res.status);
      }
      return (await res.json()) as ResumeBank;
    })().catch((err) => {
      bankPromise = null;
      throw err;
    });
  }
  return bankPromise;
}

export function resetBankCache(): void {
  bankPromise = null;
}

export async function listPeople(): Promise<Person[]> {
  const res = await apiFetch("/api/people");
  if (!res.ok) throw new ApiError(`Failed to load people (HTTP ${res.status}).`, res.status);
  return (await res.json()) as Person[];
}

async function writePerson(path: string, method: string, body: PersonInput): Promise<Person> {
  const res = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`Failed to save person (HTTP ${res.status}).`, res.status);
  return (await res.json()) as Person;
}

export function createPerson(body: PersonInput): Promise<Person> {
  return writePerson("/api/people", "POST", body);
}

export function updatePerson(id: string, body: PersonInput): Promise<Person> {
  return writePerson(`/api/people/${encodeURIComponent(id)}`, "PUT", body);
}

export async function deletePerson(id: string): Promise<void> {
  const res = await apiFetch(`/api/people/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(`Failed to delete person (HTTP ${res.status}).`, res.status);
}
