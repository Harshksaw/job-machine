// Same-origin API client. The bearer token is the only secret the browser
// holds — it lives in localStorage and rides in the Authorization header on
// every /api call. It is NEVER placed in a URL/query string (that is why the
// PDF is fetched here and handed to the iframe as a blob URL).

import type { Application, ResumeBank, TailoredResumeMeta } from "./types";

const TOKEN_KEY = "rts_token";

/** Fired when any /api call returns 401 so the app can drop back to the
 * token-entry screen. */
export const UNAUTHORIZED_EVENT = "rts:unauthorized";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function authedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...init, headers });

  if (res.status === 401) {
    // Bad/expired token: forget it and tell the app to re-prompt.
    clearToken();
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError("Unauthorized — token was rejected.", 401);
  }
  return res;
}

export async function fetchApplications(): Promise<Application[]> {
  const res = await authedFetch("/api/applications");
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
  const res = await authedFetch(`/api/tailored/${encodeURIComponent(id)}`);
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

export async function fetchTailoredPdf(id: string): Promise<Blob> {
  const res = await authedFetch(`/api/tailored/${encodeURIComponent(id)}/pdf`);
  if (!res.ok) {
    throw new ApiError(`Failed to load PDF (HTTP ${res.status}).`, res.status);
  }
  return res.blob();
}

// The resume bank rarely changes across a session, so cache the in-flight
// promise once. A failed fetch resets the cache so it can be retried.
let bankPromise: Promise<ResumeBank> | null = null;

export function loadResumeBank(): Promise<ResumeBank> {
  if (!bankPromise) {
    bankPromise = (async () => {
      const res = await authedFetch("/api/resume-bank");
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
