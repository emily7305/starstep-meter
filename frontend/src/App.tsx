import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchHealth, fetchJobStatus, fetchReport, isAbortError, uploadAudio } from "./api";
import { HealthReadout, type Health } from "./components/HealthReadout";
import { ReportView } from "./components/ReportView";
import { StageTrack, trackFor, type TrackPosition } from "./components/StageTrack";
import { Timeline } from "./components/Timeline";
import { UploadPanel, type UploadProgress } from "./components/UploadPanel";
import { failureText, stageLabel } from "./format";
import { pollJob } from "./poll";
import type { JobStage, JobStatus } from "./types/api";
import type { TimingReport } from "./types/timingReport";

interface RunState {
  busy: boolean;
  progress: UploadProgress | null;
  track: TrackPosition;
  stage: JobStage | null;
  errorText: string | null;
}

const IDLE: RunState = {
  busy: false,
  progress: null,
  track: { finished: 0, at: "waiting" },
  stage: null,
  errorText: null,
};

function offlineOr(err: unknown, fallback: (message: string) => string): string {
  if (err instanceof ApiError && err.offline) return "backend offline";
  return fallback(err instanceof Error ? err.message : "unknown error");
}

function applyStatus(run: RunState, status: JobStatus): RunState {
  if (status.status === "failed") {
    return {
      ...run,
      busy: false,
      stage: status.stage,
      track: trackFor(status),
      errorText: status.error ? failureText(status.error) : "analysis failed",
    };
  }
  return { ...run, stage: status.stage, track: trackFor(status) };
}

function StarMark() {
  return (
    <svg className="wordmark__star" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        d="M12 2C12.6 8.4 15.6 11.4 22 12C15.6 12.6 12.6 15.6 12 22C11.4 15.6 8.4 12.6 2 12C8.4 11.4 11.4 8.4 12 2Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function App() {
  const [health, setHealth] = useState<Health>({ kind: "loading" });
  const [file, setFile] = useState<File | null>(null);
  const [run, setRun] = useState<RunState>(IDLE);
  const [report, setReport] = useState<TimingReport | null>(null);
  const runAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then(
      (status) => setHealth({ kind: "ok", status }),
      (err: unknown) => {
        if (!isAbortError(err)) setHealth({ kind: "offline" });
      },
    );
    return () => controller.abort();
  }, []);

  // unmount stops the upload and the polling loop together
  useEffect(() => () => runAbort.current?.abort(), []);

  const choose = useCallback((next: File) => {
    runAbort.current?.abort();
    runAbort.current = null;
    setFile(next);
    setReport(null);
    setRun(IDLE);
  }, []);

  const analyze = useCallback(async () => {
    if (file === null) return;

    runAbort.current?.abort();
    const controller = new AbortController();
    runAbort.current = controller;
    const { signal } = controller;

    setReport(null);
    setRun({ ...IDLE, busy: true, progress: { fraction: 0, complete: false }, track: { finished: 0, at: "active" } });

    // decides which message an error gets, upload errors read differently
    let uploading = true;

    try {
      const { job_id } = await uploadAudio(
        file,
        (fraction) => {
          if (!signal.aborted) setRun((r) => ({ ...r, progress: { fraction, complete: false } }));
        },
        signal,
      );
      uploading = false;
      setRun((r) => ({ ...r, progress: { fraction: 1, complete: true }, track: { finished: 1, at: "waiting" } }));

      const last = await pollJob(() => fetchJobStatus(job_id, signal), {
        intervalMs: 1000,
        signal,
        onUpdate: (status) => setRun((r) => applyStatus(r, status)),
      });
      // applyStatus already put the failure on screen
      if (last.status === "failed") return;

      const next = await fetchReport(job_id, signal);
      setReport(next);
      setRun((r) => ({ ...r, busy: false }));
    } catch (err) {
      // aborted means a new file or an unmount took over, that run is no longer ours to touch
      if (isAbortError(err)) return;
      const errorText = uploading
        ? offlineOr(err, (detail) => `upload rejected — ${detail}`)
        : offlineOr(err, (detail) => detail);
      setRun((r) => ({
        ...r,
        busy: false,
        errorText,
        // cap at 4 so a failed report fetch lands on the done pill, not past the end
        track: { finished: Math.min(r.track.finished, 4), at: "failed" },
      }));
    }
  }, [file]);

  let statusText = "";
  if (run.errorText !== null) statusText = run.errorText;
  else if (run.stage !== null) statusText = stageLabel(run.stage);

  return (
    <>
      <header className="header">
        <h1 className="wordmark">
          <StarMark />
          starstep-meter
        </h1>
        <HealthReadout health={health} />
      </header>

      <Timeline report={report} />

      <main className="content">
        <section className="column" aria-labelledby="source-label">
          <h2 className="section-label" id="source-label">
            source
          </h2>
          <UploadPanel file={file} busy={run.busy} progress={run.progress} onChoose={choose} onAnalyze={analyze} />
          <StageTrack position={run.track} message={statusText} />
        </section>

        <section className="column" aria-labelledby="report-label">
          <h2 className="section-label" id="report-label">
            report
          </h2>
          <ReportView report={report} />
        </section>
      </main>
    </>
  );
}
