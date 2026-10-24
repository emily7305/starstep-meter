// helpers around job ids and the recent jobs list, plain functions so they test without a dom

export const JOB_PARAM = "job";

// same pattern the backend checks before an id goes into a path
const JOB_ID = /^[0-9a-f]{32}$/;

export function jobIdFromSearch(search: string): string | null {
  const value = new URLSearchParams(search).get(JOB_PARAM);
  return value !== null && JOB_ID.test(value) ? value : null;
}

// keeps the other params, "" when nothing is left so the url doesn't end in a bare "?"
export function searchWithJob(search: string, jobId: string | null): string {
  const params = new URLSearchParams(search);
  if (jobId === null) params.delete(JOB_PARAM);
  else params.set(JOB_PARAM, jobId);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

// subtle only exists in secure contexts, 127.0.0.1 counts but a lan address doesn't
// null then means the match lookup is skipped, not that the upload is blocked
export async function fileSha256(
  file: Blob,
  subtle: SubtleCrypto | undefined = globalThis.crypto?.subtle,
): Promise<string | null> {
  if (subtle === undefined) return null;
  // audio files, a few tens of MB at most, so reading the whole thing is fine
  const digest = await subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

// local time, the backend stamps utc
export function formatJobDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return `${day} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function formatEditCount(n: number): string {
  if (n === 0) return "no edits";
  return `${n} ${n === 1 ? "edit" : "edits"}`;
}
