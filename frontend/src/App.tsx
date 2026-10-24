import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  audioUrl,
  fetchBeats,
  fetchHealth,
  fetchJobStatus,
  fetchReport,
  isAbortError,
  patchOffset,
  uploadAudio,
} from "./api";
import { HealthReadout, type Health } from "./components/HealthReadout";
import { ReportView } from "./components/ReportView";
import { StageTrack, trackFor, type TrackPosition } from "./components/StageTrack";
import { Timeline } from "./components/Timeline";
import { UploadPanel, type UploadProgress } from "./components/UploadPanel";
import { failureText, stageLabel } from "./format";
import { nudged, OFFSET_FIELD, OffsetSaver, type SaveState, withOffsetEdit } from "./offset";
import { pollJob } from "./poll";
import type { JobStage, JobStatus } from "./types/api";
import type { BeatsFile } from "./types/beats";
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

// what the analysis found, the first offset edit remembers it as its old value
function autoOffset(report: TimingReport | null): number | null {
  if (report === null) return null;
  const first = report.edits.find((e) => e.field === OFFSET_FIELD);
  return first !== undefined && typeof first.old === "number" ? first.old : report.beat_offset_ms;
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
  const [beats, setBeats] = useState<BeatsFile | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  // the offset on screen while it's being adjusted, null once the server has it
  const [draft, setDraft] = useState<number | null>(null);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "saved" });
  const runAbort = useRef<AbortController | null>(null);
  const saver = useRef<OffsetSaver | null>(null);
  // key repeat fires faster than renders land, so nudges read these instead of state
  const reportRef = useRef<TimingReport | null>(null);
  const draftRef = useRef<number | null>(null);
  reportRef.current = report;
  draftRef.current = draft;

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

  const hasReport = report !== null;
  useEffect(() => {
    const current = reportRef.current;
    if (jobId === null || current === null) return;
    const next = new OffsetSaver({
      saved: current.beat_offset_ms,
      send: async (value) => {
        const before = reportRef.current;
        // the edit shows up straight away, the server's copy replaces it when the patch returns
        if (before !== null) setReport(withOffsetEdit(before, value, new Date()));
        try {
          return await patchOffset(jobId, value);
        } catch (err) {
          if (before !== null) setReport(before);
          throw err instanceof ApiError && err.offline ? new Error("backend offline") : err;
        }
      },
      onSaved: (saved) => {
        setReport(saved);
        setDraft((d) => (d === saved.beat_offset_ms ? null : d));
      },
      onState: setSaveState,
    });
    saver.current = next;
    setSaveState({ kind: "saved" });
    return () => {
      next.dispose();
      saver.current = null;
    };
  }, [jobId, hasReport]);

  const resetResult = useCallback(() => {
    setReport(null);
    setBeats(null);
    setJobId(null);
    setDraft(null);
  }, []);

  const nudge = useCallback((steps: number) => {
    const base = draftRef.current ?? reportRef.current?.beat_offset_ms ?? null;
    if (base === null) return;
    const next = nudged(base, steps);
    draftRef.current = next;
    setDraft(next);
    saver.current?.push(next);
  }, []);

  const retrySave = useCallback(() => void saver.current?.flush(), []);

  const choose = useCallback(
    (next: File) => {
      runAbort.current?.abort();
      runAbort.current = null;
      setFile(next);
      resetResult();
      setRun(IDLE);
    },
    [resetResult],
  );

  const analyze = useCallback(async () => {
    if (file === null) return;

    runAbort.current?.abort();
    const controller = new AbortController();
    runAbort.current = controller;
    const { signal } = controller;

    resetResult();
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
      // the grid still draws without the beats file, it just can't tell the bar length
      const nextBeats = await fetchBeats(job_id, signal).catch((err: unknown) => {
        if (isAbortError(err)) throw err;
        return null;
      });
      setReport(next);
      setBeats(nextBeats);
      setJobId(job_id);
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
        // cap at 6 so a failed report fetch lands on the done pill, not past the end
        track: { finished: Math.min(r.track.finished, 6), at: "failed" },
      }));
    }
  }, [file, resetResult]);

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

      <Timeline
        audioUrl={jobId === null ? null : audioUrl(jobId)}
        report={report}
        beats={beats}
        offsetMs={draft ?? report?.beat_offset_ms ?? null}
        autoOffsetMs={autoOffset(report)}
        saveState={saveState}
        onNudge={nudge}
        onRetry={retrySave}
      />

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
          <ReportView report={report} beats={beats} />
        </section>
      </main>
    </>
  );
}
