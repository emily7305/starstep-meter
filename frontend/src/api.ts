import { downloadName, type ExportChoice, exportPath } from "./exportOptions";
import type { HealthStatus, JobStatus, JobSummary, TempoEditOp, UploadResponse } from "./types/api";
import type { BeatsFile } from "./types/beats";
import type { TimingReport } from "./types/timingReport";

export class ApiError extends Error {
  readonly status: number;
  // true when the backend never answered (or the proxy answered for it)
  readonly offline: boolean;

  constructor(message: string, status: number, offline = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.offline = offline;
  }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

function offlineError(status = 0): ApiError {
  return new ApiError("backend offline", status, true);
}

function parseDetail(body: string): string | null {
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      return typeof parsed.detail === "string" ? parsed.detail : null;
    }
  } catch {
    // not json, falls through
  }
  return null;
}

function errorFromResponse(status: number, body: string): ApiError {
  const detail = parseDetail(body);
  if (detail !== null) return new ApiError(detail, status);
  // vite's proxy answers 5xx with an empty body when nothing is listening on :8000
  if (status >= 500) return offlineError(status);
  return new ApiError(`http ${status}`, status);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  let text: string;
  let status: number;
  let ok: boolean;
  try {
    const res = await fetch(path, { ...init, headers: { accept: "application/json", ...init.headers } });
    status = res.status;
    ok = res.ok;
    text = await res.text();
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw offlineError();
  }
  if (!ok) throw errorFromResponse(status, text);
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("unexpected response from server", status);
  }
}

function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { signal });
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return getJson<HealthStatus>("/api/health", signal);
}

export function fetchJobStatus(jobId: string, signal?: AbortSignal): Promise<JobStatus> {
  return getJson<JobStatus>(`/api/jobs/${encodeURIComponent(jobId)}`, signal);
}

export function fetchReport(jobId: string, signal?: AbortSignal): Promise<TimingReport> {
  return getJson<TimingReport>(`/api/jobs/${encodeURIComponent(jobId)}/report`, signal);
}

export function fetchBeats(jobId: string, signal?: AbortSignal): Promise<BeatsFile> {
  return getJson<BeatsFile>(`/api/jobs/${encodeURIComponent(jobId)}/beats`, signal);
}

export function patchTempo(jobId: string, op: TempoEditOp, signal?: AbortSignal): Promise<TimingReport> {
  return requestJson<TimingReport>(`/api/jobs/${encodeURIComponent(jobId)}/report`, {
    method: "PATCH",
    signal,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(op),
  });
}

// newest first, sha256 narrows it to the jobs for one exact file
export function listJobs(sha256?: string, signal?: AbortSignal): Promise<JobSummary[]> {
  const query = sha256 === undefined ? "" : `?sha256=${encodeURIComponent(sha256)}`;
  return getJson<JobSummary[]>(`/api/jobs${query}`, signal);
}

// keep: the backend keeps the manual edits and runs the analysis over. fresh: it drops them, the
// edit log keeps a record of what went
export type ReanalyzeMode = "keep" | "fresh";

export function reanalyzeUrl(jobId: string, mode: ReanalyzeMode): string {
  const base = `/api/jobs/${encodeURIComponent(jobId)}/reanalyze`;
  return mode === "keep" ? base : `${base}?mode=fresh`;
}

// same job id again
export function reanalyzeJob(jobId: string, mode: ReanalyzeMode = "keep", signal?: AbortSignal): Promise<UploadResponse> {
  return requestJson<UploadResponse>(reanalyzeUrl(jobId, mode), { method: "POST", signal });
}

// stops at the next stage. a first analysis is deleted, a re-analysis goes back to its last report
export function cancelJob(jobId: string, signal?: AbortSignal): Promise<UploadResponse> {
  return requestJson<UploadResponse>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", signal });
}

// the click track with drums the backend makes, analyzed like an upload
export function createDemo(signal?: AbortSignal): Promise<UploadResponse> {
  return requestJson<UploadResponse>("/api/demo", { method: "POST", signal });
}

// a 204 has no body, so not requestJson. 409 while the job is queued or running
export async function deleteJob(jobId: string, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      signal,
      headers: { accept: "application/json" },
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw offlineError();
  }
  if (!res.ok) throw errorFromResponse(res.status, await res.text());
}

export interface ExportFile {
  blob: Blob;
  filename: string;
}

// fetched rather than linked, so a refused export shows its reason instead of saving it as the file
export async function fetchExport(jobId: string, choice: ExportChoice, signal?: AbortSignal): Promise<ExportFile> {
  let res: Response;
  try {
    res = await fetch(exportPath(jobId, choice), { signal, headers: { accept: "application/json" } });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw offlineError();
  }
  if (!res.ok) throw errorFromResponse(res.status, await res.text());
  const fallback = `${jobId}.timing.json`;
  return { blob: await res.blob(), filename: downloadName(res.headers.get("content-disposition"), fallback) };
}

// the decoded wav the analysis ran on, so the waveform shares the report's timeline
export function audioUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/audio`;
}

function parseJobId(body: string): string | null {
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === "object" && parsed !== null && "job_id" in parsed) {
      return typeof parsed.job_id === "string" ? parsed.job_id : null;
    }
  } catch {
    // same as above, a bad body just means no id
  }
  return null;
}

// fetch can't report upload progress, so this one stays on xhr
// onProgress gets 0..1
export function uploadAudio(
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("upload aborted", "AbortError"));
      return;
    }

    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener("abort", onAbort);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) {
        const jobId = parseJobId(xhr.responseText);
        if (jobId === null) {
          reject(new ApiError("unexpected response from server", xhr.status));
          return;
        }
        onProgress(1);
        resolve({ job_id: jobId });
      } else {
        reject(errorFromResponse(xhr.status, xhr.responseText));
      }
    };
    xhr.onerror = () => {
      cleanup();
      reject(offlineError());
    };
    xhr.onabort = () => {
      cleanup();
      reject(new DOMException("upload aborted", "AbortError"));
    };

    signal?.addEventListener("abort", onAbort, { once: true });

    const body = new FormData();
    body.append("file", file);
    xhr.open("POST", "/api/jobs");
    xhr.setRequestHeader("accept", "application/json");
    xhr.send(body);
  });
}
