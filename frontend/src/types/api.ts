// hand-written on purpose, these mirror the backend routes and aren't in the json schema

export type JobState = "queued" | "running" | "done" | "failed";

export type JobStage = "queued" | "decode" | "trim" | "beats" | "snap" | "tempo" | "done" | "failed";

// a job can't fail "at" done or failed, so those two are left out
export type FailedStage = "queued" | "decode" | "trim" | "beats" | "snap" | "tempo";

export interface JobError {
  stage: FailedStage;
  message: string;
}

export interface JobStatus {
  status: JobState;
  stage: JobStage;
  error: JobError | null;
}

export interface UploadResponse {
  job_id: string;
}

export interface HealthStatus {
  status: "ok";
  ffmpeg: boolean;
  ffprobe: boolean;
  madmom: boolean;
}
