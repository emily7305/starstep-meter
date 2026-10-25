// hand-written on purpose, these mirror the backend routes and aren't in the json schema

export type JobState = "queued" | "running" | "done" | "failed";

export type JobStage = "queued" | "decode" | "trim" | "beats" | "snap" | "tempo" | "meter" | "check" | "done" | "failed";

// a job can't fail "at" done or failed, so those two are left out
export type FailedStage = "queued" | "decode" | "trim" | "beats" | "snap" | "tempo" | "meter" | "check";

export interface JobError {
  stage: FailedStage;
  message: string;
}

export interface JobStatus {
  status: JobState;
  stage: JobStage;
  error: JobError | null;
  // a failed job that still has the last good report from before a failed re-analysis
  report_available: boolean;
}

export interface UploadResponse {
  job_id: string;
}

export interface HealthStatus {
  status: "ok";
  ffmpeg: boolean;
  ffprobe: boolean;
  // true only when it's installed and imports
  madmom: boolean;
  // why an installed madmom doesn't import, null when it works or isn't installed
  madmom_error: string | null;
}

export interface JobSummary {
  job_id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  // iso utc string
  created_at: string;
  // when a re-analysis last finished, iso utc, null when there hasn't been one
  reanalyzed_at: string | null;
  status: JobState;
  // null when there's no report to count
  edits: number | null;
  // the generated demo track, not a song
  demo: boolean;
}

// one edit per request, same shapes as the patch bodies
export type TempoEditOp =
  | { op: "set_anchor"; segment: number; anchor_ms: number }
  | { op: "set_bpm"; segment: number; bpm: number }
  // a manual segment back to what the latest analysis has there, x2 or /2 kept
  | { op: "reset_segment"; segment: number }
  | { op: "split"; at_ms: number }
  // splits at both ends of one of the segment's ratio_merged sections, as one edit
  | { op: "split_out"; segment: number; section: number }
  | { op: "merge"; segment: number }
  // this segment takes the neighbour's bpm and anchor and joins it
  | { op: "match"; segment: number; side: "previous" | "next" }
  // segment indexes the meter map here, bars restart at a split
  | { op: "set_meter"; segment: number; numerator: number; denominator: number }
  | { op: "split_meter"; at_ms: number }
  | { op: "merge_meter"; segment: number }
  // suggestion indexes notation_suggestions
  | { op: "apply_suggestion"; suggestion: number }
  | { op: "dismiss_suggestion"; suggestion: number };
