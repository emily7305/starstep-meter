import type { JobError, JobStage } from "./types/api";

export function formatMs(v: number): string {
  return `${v.toFixed(1)} ms`;
}

// offsets get all three decimals, 1 ms steps on a value like 136.774 should stay readable
export function formatFineMs(v: number): string {
  return `${v.toFixed(3)} ms`;
}

export function formatDeltaMs(v: number): string {
  // -0.000 reads like a bug, and a real minus sign lines up with the plus in mono
  const value = Math.abs(v) < 0.0005 ? 0 : v;
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(3)} ms`;
}

export function formatBpm(v: number): string {
  return `${v.toFixed(2)} bpm`;
}

export function formatHz(v: number): string {
  return `${v} hz`;
}

// 1024 steps, same as what the os file dialog tends to show
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let value = n / 1024;
  let unit = 0;
  // compare the rounded value so 1023.96 kb doesn't print as 1024.0 kb
  while (Number(value.toFixed(1)) >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

const STAGE_LABELS: Record<JobStage, string> = {
  queued: "queued",
  decode: "decoding",
  trim: "trimming",
  beats: "tracking beats",
  snap: "snapping to onsets",
  tempo: "fitting tempo",
  meter: "finding meter",
  check: "cross-checking beats",
  done: "done",
  failed: "failed",
};

export function stageLabel(stage: JobStage): string {
  return STAGE_LABELS[stage];
}

// the two missing-binary messages are the ones people can actually fix, so they get a hint
const HINTS: Record<string, string> = {
  "ffmpeg not found on PATH": "check that ffmpeg is on PATH",
  "ffprobe not found on PATH": "check that ffprobe is on PATH",
};

function hintFor(error: JobError): string {
  return HINTS[error.message] ?? error.message;
}

export function failureText(error: JobError): string {
  return `analysis failed at ${error.stage} — ${hintFor(error)}`;
}

// the report on screen is the one from before the run that failed
export function reanalysisFailureText(error: JobError): string {
  return `re-analysis failed at ${error.stage} — ${hintFor(error)}. showing the last good report`;
}
