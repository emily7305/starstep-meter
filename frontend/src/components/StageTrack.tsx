import type { FailedStage, JobError, JobStatus } from "../types/api";

const STEPS = ["upload", "decode", "trim", "beats", "snap", "tempo", "meter", "check", "done"] as const;

// finished = how many pills from the left are done
// at = what the next pill (index finished) is doing
export interface TrackPosition {
  finished: number;
  at: "waiting" | "active" | "failed";
}

// queued has no pill of its own, a failure there lands on decode since that's the next one
const FAILED_INDEX: Record<FailedStage, number> = {
  queued: 1,
  decode: 1,
  trim: 2,
  beats: 3,
  snap: 4,
  tempo: 5,
  meter: 6,
  check: 7,
};

function failedPosition(error: JobError | null): TrackPosition {
  return { finished: error ? FAILED_INDEX[error.stage] : 1, at: "failed" };
}

export function trackFor(status: JobStatus): TrackPosition {
  if (status.status === "failed") return failedPosition(status.error);
  if (status.status === "done") return { finished: STEPS.length, at: "waiting" };
  switch (status.stage) {
    case "decode":
      return { finished: 1, at: "active" };
    case "trim":
      return { finished: 2, at: "active" };
    case "beats":
      return { finished: 3, at: "active" };
    case "snap":
      return { finished: 4, at: "active" };
    case "tempo":
      return { finished: 5, at: "active" };
    case "meter":
      return { finished: 6, at: "active" };
    case "check":
      return { finished: 7, at: "active" };
    default:
      // queued, upload is finished but nothing has picked the job up yet
      return { finished: 1, at: "waiting" };
  }
}

type PillState = "pending" | "current" | "finished" | "failed";

function pillState(position: TrackPosition, index: number): PillState {
  if (index < position.finished) return "finished";
  if (index > position.finished) return "pending";
  if (position.at === "active") return "current";
  if (position.at === "failed") return "failed";
  return "pending";
}

const STATE_TEXT: Record<PillState, string> = {
  pending: "pending",
  current: "in progress",
  finished: "finished",
  failed: "failed",
};

interface Props {
  position: TrackPosition;
  message: string;
}

export function StageTrack({ position, message }: Props) {
  return (
    <div className="track">
      <ol className="track__pills" aria-label="progress">
        {STEPS.map((step, index) => {
          const state = pillState(position, index);
          return (
            <li
              key={step}
              className="pill"
              data-state={state}
              aria-current={state === "current" ? "step" : undefined}
            >
              {state === "finished" && (
                <svg className="pill__check" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                  <path
                    d="M2 6.4L4.8 9L10 3.2"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
              {step}
              <span className="sr-only"> {STATE_TEXT[state]}</span>
            </li>
          );
        })}
      </ol>
      <p className="track__status" data-failed={position.at === "failed"} aria-live="polite">
        {message}
      </p>
    </div>
  );
}
