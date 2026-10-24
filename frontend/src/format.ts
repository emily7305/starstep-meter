import type { JobError, JobStage } from "./types/api";

export function formatMs(v: number): string {
  return `${v.toFixed(1)} ms`;
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

export function failureText(error: JobError): string {
  const hint = HINTS[error.message] ?? error.message;
  return `analysis failed at ${error.stage} — ${hint}`;
}
