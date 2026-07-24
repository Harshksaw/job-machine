// Same-origin API client. The service is local-only and unauthenticated, so
// requests are plain fetch with no Authorization header.

import type { Application, ResumeBank, TailoredResumeMeta } from "./types";

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
