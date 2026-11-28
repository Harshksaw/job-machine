// Same-origin API client. The service is local-only and unauthenticated, so
// requests are plain fetch with no Authorization header.

import { formatApiDetail } from "./lib/agents";
import type {
  AdapterStatus,
  ApplicationAnswerInput,
  FollowUpNudge,
  JobActivityInput,
  JobDecision,
  JobSummary,
  JobWorkspace,
  JobWorkspaceInput,
  Person,
  PersonInput,
  PipelineConfig,
  PipelineEnqueueResult,
  PipelineFunnel,
  PipelineRunDetail,
  PipelineRunSummary,
  PipelineStats,
  PipelineStep,
  PipelineVersion,
  PipelineWorkerStatus,
  ResumeBank,
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

export function listFollowUpNudges(): Promise<FollowUpNudge[]> {
  return jsonRequest<FollowUpNudge[]>(
    "/api/jobs/follow-ups",
    {},
    "Failed to load follow up queue."
  );
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

// Search tab. POSTs carry X-Job-Machine so a cross site page cannot trigger them.
export interface SearchOptions {
  presets: { id: string; label: string; stage: string; default_limit: number }[];
  // superseded_by is set when the orchestrator pipeline replaced the task (M7).
  tasks: { id: string; label: string; superseded_by?: string }[];
  tools: string[];
}

export interface SearchUsage {
  jobs_used: number;
  requests_used: number;
  jobs_left: number;
  requests_left: number;
  configured: boolean;
  runs: { at: string; preset: string; fetched: number; new: number }[];
}

export interface SearchResult {
  fetched: number;
  new: { id: string; company: string; role: string }[];
  duplicates: string[];
  usage: SearchUsage;
}

export interface AgentRun {
  log: string;
  started: string;
  tool: string;
  task: string;
  tail: string;
}

const DASHBOARD_POST = {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-Job-Machine": "dashboard" },
};

export function getSearchOptions(): Promise<SearchOptions> {
  return jsonRequest("/api/search/presets", {}, "Failed to load search presets.");
}

export function getSearchUsage(): Promise<SearchUsage> {
  return jsonRequest("/api/search/usage", {}, "Failed to load search usage.");
}

export function runSearch(preset: string, limit: number, timeFrame: string): Promise<SearchResult> {
  return jsonRequest(
    "/api/search/run",
    { ...DASHBOARD_POST, body: JSON.stringify({ preset, limit, time_frame: timeFrame }) },
    "Search failed."
  );
}

export function startAgent(
  tool: string,
  task: string,
  jobId?: string
): Promise<{ pid: number; log: string }> {
  return jsonRequest(
    "/api/agents/run",
    { ...DASHBOARD_POST, body: JSON.stringify({ tool, task, job_id: jobId ?? null }) },
    "Failed to start the agent."
  );
}

export function listAgentRuns(): Promise<AgentRun[]> {
  return jsonRequest("/api/agents/runs", {}, "Failed to load agent runs.");
}

export interface ResearchItem {
  id: string;
  preset: string;
  source: string;
  company: string;
  role: string;
  url: string;
  location: string;
  remote_scope: string;
  open_to_canada: boolean | null;
  salary: string;
  posted: string;
  status: string;
  tracked_dossier: string | null;
}

export function listResearch(status = "new"): Promise<ResearchItem[]> {
  return jsonRequest(`/api/research?status=${encodeURIComponent(status)}`, {}, "Failed to load research.");
}

export function promoteResearch(id: string): Promise<{ dossier_id: string }> {
  return jsonRequest(`/api/research/${encodeURIComponent(id)}/promote`, { ...DASHBOARD_POST }, "Failed to promote.");
}

export function dismissResearch(id: string): Promise<{ ok: boolean }> {
  return jsonRequest(`/api/research/${encodeURIComponent(id)}/dismiss`, { ...DASHBOARD_POST }, "Failed to dismiss.");
}

export interface SystemStats {
  generated_at: string;
  totals: {
    dossiers: number;
    applied: number;
    responded: number;
    rejected: number;
    waiting: number;
    response_rate: number | null;
  };
  by_status: Record<string, number>;
  by_source: { source: string; applied: number; responded: number; rejected: number; response_rate: number | null }[];
  by_fit: { fit: number; tracked: number; applied: number; responded: number; response_rate: number | null }[];
  weekly: { week: string; applied: number }[];
  backlog: { strong_unapplied: number; research_new: number };
  people: Record<string, number>;
  ai_usage: {
    generated_at: string | null;
    providers: {
      provider: string;
      day: number;
      week: number;
      calls_day: number;
      day_budget: number | null;
      week_budget: number | null;
    }[];
    agents?: {
      tool: string;
      status: "ok" | "blocked" | "idle";
      label: string;
      detail: string;
      at: string | null;
    }[];
  } | null;
  service: { started_at: string; database: string };
}

export interface ConnectionInfo {
  id: string;
  label: string;
  what: string;
}

export interface ConnectionResult {
  id: string;
  status: "ok" | "warn" | "fail";
  detail: string;
  ms: number;
}

export interface TelemetrySpan {
  name: string;
  kind: "request" | "call";
  status: number | null;
  duration_ms: number;
  started_at: string;
  error: boolean;
  trace_id: string;
}

export interface TelemetrySummary {
  enabled: boolean;
  service: string;
  exporter: string | null;
  buffered: number;
  buffer_size: number;
  since: string | null;
  routes: {
    name: string;
    kind: "request" | "call";
    count: number;
    errors: number;
    p50_ms: number;
    p95_ms: number;
    max_ms: number;
  }[];
  recent_errors: TelemetrySpan[];
  slowest: TelemetrySpan[];
}

export function getSystemStats(refresh = false): Promise<SystemStats> {
  return jsonRequest(`/api/system/stats${refresh ? "?refresh=true" : ""}`, {}, "Failed to load stats.");
}

export function listConnections(): Promise<ConnectionInfo[]> {
  return jsonRequest("/api/system/connections", {}, "Failed to load connections.");
}

export function checkConnection(id: string): Promise<ConnectionResult> {
  return jsonRequest(
    `/api/system/connections/${encodeURIComponent(id)}/check`,
    { ...DASHBOARD_POST },
    "Check failed."
  );
}

export function getTelemetry(): Promise<TelemetrySummary> {
  return jsonRequest("/api/system/telemetry", {}, "Failed to load telemetry.");
}

// Agents and models settings (/api/pipeline/*). Writes carry X-Job-Machine like the
// other dashboard writes. A rejected save keeps every validation line in `lines`.
export class PipelineError extends ApiError {
  lines: string[];
  constructor(lines: string[], status: number) {
    super(lines.join("; "), status);
    this.name = "PipelineError";
    this.lines = lines;
  }
}

async function pipelineRequest<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let lines: string[] = [];
    try {
      lines = formatApiDetail(((await res.json()) as { detail?: unknown }).detail);
    } catch {
      // not JSON; fall back below
    }
    throw new PipelineError(lines.length ? lines : [`${fallback} (HTTP ${res.status})`], res.status);
  }
  return (await res.json()) as T;
}

const DASHBOARD_WRITE = { "Content-Type": "application/json", "X-Job-Machine": "dashboard" };

export function getPipelineConfig(): Promise<PipelineConfig> {
  return pipelineRequest("/api/pipeline/config", {}, "Failed to load agent settings.");
}

export function savePipelineConfig(config: PipelineConfig): Promise<PipelineConfig> {
  return pipelineRequest(
    "/api/pipeline/config",
    { method: "PUT", headers: DASHBOARD_WRITE, body: JSON.stringify(config) },
    "Failed to save agent settings."
  );
}

export function listPipelineVersions(): Promise<PipelineVersion[]> {
  return pipelineRequest("/api/pipeline/config/versions", {}, "Failed to load version history.");
}

export function rollbackPipelineConfig(version: number): Promise<PipelineConfig> {
  return pipelineRequest(
    `/api/pipeline/config/rollback/${encodeURIComponent(String(version))}`,
    { method: "POST", headers: DASHBOARD_WRITE },
    "Rollback failed."
  );
}

export function resetPipelineConfig(): Promise<PipelineConfig> {
  return pipelineRequest(
    "/api/pipeline/config/reset",
    { method: "POST", headers: DASHBOARD_WRITE },
    "Reset failed."
  );
}

export function listPipelineAdapters(): Promise<AdapterStatus[]> {
  return pipelineRequest("/api/pipeline/adapters", {}, "Failed to load adapters.");
}

export function listPipelineSteps(): Promise<PipelineStep[]> {
  return pipelineRequest("/api/pipeline/steps", {}, "Failed to load steps.");
}

export interface AdapterTestResponse {
  adapter: string;
  outcome: string;
  error: string;
  model: string;
  duration_ms: number;
  attempt_id: string;
}

export function testPipelineAdapter(name: string): Promise<AdapterTestResponse> {
  return pipelineRequest(
    `/api/pipeline/adapters/${encodeURIComponent(name)}/test`,
    { method: "POST", headers: DASHBOARD_WRITE },
    "Test failed."
  );
}

// Pipeline runs (M6). Runs only queue here; the worker pool executes them when
// PIPELINE_WORKERS > 0 on the service.
export function listPipelineRuns(
  params: { job_id?: string; pipeline?: string; status?: string; limit?: number } = {}
): Promise<PipelineRunSummary[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query}` : "";
  return pipelineRequest(`/api/pipeline/runs${suffix}`, {}, "Failed to load pipeline runs.");
}

export function getPipelineRun(id: string): Promise<PipelineRunDetail> {
  return pipelineRequest(`/api/pipeline/runs/${encodeURIComponent(id)}`, {}, "Failed to load the run.");
}

export function enqueuePipelineRuns(pipeline: string, jobIds: string[] = []): Promise<PipelineEnqueueResult> {
  return pipelineRequest(
    "/api/pipeline/runs",
    { method: "POST", headers: DASHBOARD_WRITE, body: JSON.stringify({ pipeline, job_ids: jobIds }) },
    "Failed to queue the run."
  );
}

export function retryPipelineRun(id: string, step?: string): Promise<{ run: PipelineRunDetail; reset: string[] }> {
  return pipelineRequest(
    `/api/pipeline/runs/${encodeURIComponent(id)}/retry`,
    { method: "POST", headers: DASHBOARD_WRITE, body: JSON.stringify(step ? { step } : {}) },
    "Retry failed."
  );
}

export function cancelPipelineRun(id: string): Promise<{ run: PipelineRunDetail; killed: number }> {
  return pipelineRequest(
    `/api/pipeline/runs/${encodeURIComponent(id)}/cancel`,
    { method: "POST", headers: DASHBOARD_WRITE },
    "Cancel failed."
  );
}

export function getPipelineStats(since = ""): Promise<PipelineStats> {
  const suffix = since ? `?since=${encodeURIComponent(since)}` : "";
  return pipelineRequest(`/api/pipeline/stats${suffix}`, {}, "Failed to load pipeline stats.");
}

export function getPipelineWorker(): Promise<PipelineWorkerStatus> {
  return pipelineRequest("/api/pipeline/worker", {}, "Failed to load worker status.");
}

export function getPipelineFunnel(since = "", until = ""): Promise<PipelineFunnel> {
  const query = new URLSearchParams();
  if (since) query.set("since", since);
  if (until) query.set("until", until);
  const suffix = query.toString() ? `?${query}` : "";
  return pipelineRequest(`/api/pipeline/funnel${suffix}`, {}, "Failed to load the flow counts.");
}
