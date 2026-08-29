// Same-origin API client. The service is local-only and unauthenticated, so
// requests are plain fetch with no Authorization header.

import type {
  Application,
  ApplicationAnswerInput,
  JobActivityInput,
  JobDecision,
  JobSummary,
  JobWorkspace,
  JobWorkspaceInput,
  Person,
  PersonInput,
  ResumeBank,
  SheetImportResult,
  TailoredResumeMeta,
  TailorResponse,
} from "./types";

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

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const payload = (await res.json()) as { detail?: string };
    return typeof payload.detail === "string" ? payload.detail : fallback;
  } catch {
    return fallback;
  }
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
  fallback = "Request failed."
): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    throw new ApiError(await errorMessage(res, fallback), res.status);
  }
  return (await res.json()) as T;
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

export async function listPeople(company?: string, jobId?: string): Promise<Person[]> {
  const params = new URLSearchParams();
  if (company) params.set("company", company);
  if (jobId) params.set("job_id", jobId);
  const query = params.toString();
  const res = await apiFetch(query ? `/api/people?${query}` : "/api/people");
  if (!res.ok) throw new ApiError(`Failed to load people (HTTP ${res.status}).`, res.status);
  return (await res.json()) as Person[];
}

export function listJobPeople(jobId: string): Promise<Person[]> {
  return jsonRequest<Person[]>(
    `/api/jobs/${encodeURIComponent(jobId)}/people`,
    {},
    "Failed to load people for this job."
  );
}

export function addJobPerson(jobId: string, body: PersonInput, session = "Inbox"): Promise<Person> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<Person>(
    `/api/jobs/${encodeURIComponent(jobId)}/people${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to save this person on the job."
  );
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

export function listJobs(): Promise<JobSummary[]> {
  return jsonRequest<JobSummary[]>("/api/jobs", {}, "Failed to load job dossiers.");
}

export function getJob(id: string): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(id)}`,
    {},
    "Failed to load the job dossier."
  );
}

export function createJob(
  body: JobWorkspaceInput,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to create the job dossier."
  );
}

export function updateJob(
  id: string,
  body: JobWorkspaceInput,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(id)}${query}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to save the job dossier."
  );
}

export async function deleteJob(id: string): Promise<void> {
  const res = await apiFetch(`/api/jobs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new ApiError(
      await errorMessage(res, "Failed to delete the job dossier."),
      res.status
    );
  }
}

export function createJobFromApplication(
  application: Application,
  session = "Pipeline"
): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/from-application?session=${encodeURIComponent(session)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(application),
    },
    "Failed to create a dossier from this application."
  );
}

export function importJobsFromSheet(session = "Sheet import"): Promise<SheetImportResult> {
  return jsonRequest<SheetImportResult>(
    `/api/jobs/import-sheet?session=${encodeURIComponent(session)}`,
    { method: "POST" },
    "Failed to import the application sheet."
  );
}

export function addJobActivity(
  id: string,
  body: JobActivityInput
): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(id)}/activity`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to add activity."
  );
}

export function restoreJobRevision(
  id: string,
  revisionId: string,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(id)}/restore/${encodeURIComponent(revisionId)}${query}`,
    { method: "POST" },
    "Failed to restore the revision."
  );
}

export function generateJobKit(
  id: string,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(id)}/generate-kit${query}`,
    { method: "POST" },
    "Failed to generate the application kit."
  );
}

export function tailorJob(
  job: JobWorkspace,
  session = ""
): Promise<TailorResponse> {
  return jsonRequest<TailorResponse>(
    "/tailor",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jd_text: job.jd_text,
        company: job.company,
        role: job.role,
        job_url: job.job_url || null,
        job_id: job.id,
        session,
      }),
    },
    "Failed to tailor the resume."
  );
}

export function addApplicationAnswer(
  jobId: string,
  body: ApplicationAnswerInput,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(jobId)}/answers${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to add the application answer."
  );
}

export function generateApplicationAnswer(
  jobId: string,
  question: string,
  constraints: string,
  session = ""
): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(jobId)}/answers/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, constraints, session }),
    },
    "Failed to draft the application answer."
  );
}

export function updateApplicationAnswer(
  jobId: string,
  answerId: string,
  body: ApplicationAnswerInput,
  session = ""
): Promise<JobWorkspace> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(jobId)}/answers/${encodeURIComponent(answerId)}${query}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    "Failed to update the application answer."
  );
}

export async function deleteApplicationAnswer(
  jobId: string,
  answerId: string,
  session = ""
): Promise<void> {
  const query = session ? `?session=${encodeURIComponent(session)}` : "";
  const res = await apiFetch(
    `/api/jobs/${encodeURIComponent(jobId)}/answers/${encodeURIComponent(answerId)}${query}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    throw new ApiError(
      await errorMessage(res, "Failed to delete the application answer."),
      res.status
    );
  }
}

export function decideJob(
  jobId: string,
  decision: JobDecision,
  session = "Inbox"
): Promise<JobWorkspace> {
  return jsonRequest<JobWorkspace>(
    `/api/jobs/${encodeURIComponent(jobId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, session }),
    },
    "Failed to save the inbox decision."
  );
}
