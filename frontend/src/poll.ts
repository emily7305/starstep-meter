import type { JobStatus } from "./types/api";

export interface PollOptions {
  intervalMs?: number;
  signal?: AbortSignal;
  onUpdate?: (status: JobStatus) => void;
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
}

function abortError(): DOMException {
  return new DOMException("polling aborted", "AbortError");
}

function defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function changed(prev: JobStatus, next: JobStatus): boolean {
  if (prev.status !== next.status || prev.stage !== next.stage) return true;
  // error can come back as undefined if the backend leaves the key out, treat that as null
  const a = prev.error ?? null;
  const b = next.error ?? null;
  if (a === null || b === null) return a !== b;
  return a.stage !== b.stage || a.message !== b.message;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

// todo: retry once on a network blip instead of failing the whole poll
export async function pollJob(
  fetchStatus: () => Promise<JobStatus>,
  options: PollOptions = {},
): Promise<JobStatus> {
  const { intervalMs = 1000, signal, onUpdate, sleep = defaultSleep } = options;
  let previous: JobStatus | null = null;

  for (;;) {
    throwIfAborted(signal);
    const status = await fetchStatus();
    // abort can land while the request is in flight, don't report a stale update after it
    throwIfAborted(signal);

    if (previous === null || changed(previous, status)) onUpdate?.(status);
    previous = status;

    if (status.status === "done" || status.status === "failed") return status;
    await sleep(intervalMs, signal);
  }
}
