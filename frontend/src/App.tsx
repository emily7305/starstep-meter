import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  audioUrl,
  fetchBeats,
  fetchHealth,
  fetchJobStatus,
  fetchReport,
  isAbortError,
  listJobs,
  patchTempo,
  reanalyzeJob,
  uploadAudio,
} from "./api";
import { ExportPanel } from "./components/ExportPanel";
import { HealthReadout, type Health } from "./components/HealthReadout";
import { RecentJobs } from "./components/RecentJobs";
import { ReopenPrompt } from "./components/ReopenPrompt";
import { ReportView } from "./components/ReportView";
import { StageTrack, trackFor, type TrackPosition } from "./components/StageTrack";
import { Timeline } from "./components/Timeline";
import { UploadPanel, type UploadProgress } from "./components/UploadPanel";
import { ensureJapaneseFont } from "./fonts";
import { failureText, reanalysisFailureText, stageLabel } from "./format";
import { fileSha256, jobIdFromSearch, searchWithJob } from "./jobs";
import { pollJob } from "./poll";
import { EditSaver, nudged, type SaveState } from "./tempoEdits";
import { type AnchorDraft, appliedSegment, segmentAt, splitOutSegment } from "./tempoMap";
import type { JobStage, JobStatus, JobSummary, TempoEditOp } from "./types/api";
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

function failedText(status: JobStatus): string {
  if (!status.error) return "analysis failed";
  // a report to show means it was a re-analysis that failed, the first analysis has nothing to fall back on
  return status.report_available ? reanalysisFailureText(status.error) : failureText(status.error);
}

function applyStatus(run: RunState, status: JobStatus): RunState {
  if (status.status === "failed") {
    return {
      ...run,
      busy: false,
      stage: status.stage,
      track: trackFor(status),
      errorText: failedText(status),
    };
  }
  return { ...run, stage: status.stage, track: trackFor(status) };
}

// the job id lives in the url, so a reload or a shared tab reopens the same job
function setUrlJob(jobId: string | null, push: boolean): void {
  const search = searchWithJob(window.location.search, jobId);
  if (search === window.location.search) return;
  const url = `${window.location.pathname}${search}${window.location.hash}`;
  if (push) window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
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
  // what the server has, edits only ever come back from it
  const [report, setReport] = useState<TimingReport | null>(null);
  const [beats, setBeats] = useState<BeatsFile | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  // the anchor on screen while it's being nudged, null once the server has it
  const [draft, setDraft] = useState<AnchorDraft | null>(null);
  const [selected, setSelected] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>({ kind: "saved" });
  // a split, merge or match is out, segment indices are about to change under the controls
  const [reshaping, setReshaping] = useState(false);
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [jobsError, setJobsError] = useState<string | null>(null);
  // earlier jobs for the file just picked, the upload waits until one is chosen
  const [matches, setMatches] = useState<JobSummary[] | null>(null);
  const runAbort = useRef<AbortController | null>(null);
  const saver = useRef<EditSaver | null>(null);
  // key repeat fires faster than renders land, so nudges read these instead of state
  const reportRef = useRef<TimingReport | null>(null);
  const draftRef = useRef<AnchorDraft | null>(null);
  const selectedRef = useRef(0);
  reportRef.current = report;
  draftRef.current = draft;
  selectedRef.current = selected;

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

  const refreshJobs = useCallback(() => {
    listJobs().then(
      (list) => {
        setJobs(list);
        setJobsError(null);
      },
      (err: unknown) => setJobsError(offlineOr(err, (detail) => `job list failed — ${detail}`)),
    );
  }, []);
  useEffect(refreshJobs, [refreshJobs]);

  // unmount stops the upload and the polling loop together
  useEffect(() => () => runAbort.current?.abort(), []);

  useEffect(() => ensureJapaneseFont(file?.name), [file]);
  useEffect(() => ensureJapaneseFont(report?.source.filename), [report?.source.filename]);

  // a merge or a fresh report can leave the selection past the end. not while a split is out,
  // its selection points into the map that's coming back and would get pulled back to the end
  const segmentCount = report?.tempo_map.length ?? 0;
  useEffect(() => {
    if (!reshaping && segmentCount > 0 && selected >= segmentCount) setSelected(segmentCount - 1);
  }, [reshaping, segmentCount, selected]);

  const hasReport = report !== null;
  useEffect(() => {
    if (jobId === null || reportRef.current === null) return;
    const next = new EditSaver({
      send: async (op) => {
        try {
          return await patchTempo(jobId, op);
        } catch (err) {
          throw err instanceof ApiError && err.offline ? new Error("backend offline") : err;
        }
      },
      onSaved: (saved) => {
        setReport(saved);
        setDraft((d) => (d !== null && saved.tempo_map[d.segment]?.anchor_ms === d.anchorMs ? null : d));
      },
      onState: (state) => {
        setSaveState(state);
        if (state.kind === "saved" || state.kind === "failed") setReshaping(false);
      },
      savedAnchor: (segment) => reportRef.current?.tempo_map[segment]?.anchor_ms ?? null,
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
    setSelected(0);
    setReshaping(false);
  }, []);

  const nudge = useCallback((steps: number) => {
    const current = reportRef.current;
    const segment = selectedRef.current;
    const anchor = current?.tempo_map[segment]?.anchor_ms;
    if (anchor === undefined) return;
    const d = draftRef.current;
    const next = nudged(d !== null && d.segment === segment ? d.anchorMs : anchor, steps);
    const nextDraft = { segment, anchorMs: next };
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    saver.current?.nudgeAnchor(segment, next);
  }, []);

  const edit = useCallback((op: TempoEditOp) => {
    const current = reportRef.current;
    if (current === null || saver.current === null) return;
    if (op.op === "split" || op.op === "split_out" || op.op === "merge" || op.op === "match") {
      setReshaping(true);
      // keep the selection on the segment the edit was about once the indices move
      if (op.op === "split") setSelected(segmentAt(current.tempo_map, op.at_ms) + 1);
      else if (op.op === "split_out") setSelected(splitOutSegment(current.tempo_map, op.segment, op.section));
      else if (op.op === "match" && op.side === "previous") setSelected(op.segment - 1);
      else setSelected(op.segment);
    } else if (op.op === "apply_suggestion") {
      setReshaping(true);
      const suggestion = current.notation_suggestions[op.suggestion];
      if (suggestion !== undefined) setSelected(appliedSegment(current.tempo_map, suggestion));
    }
    void saver.current.submit(op);
  }, []);

  const retrySave = useCallback(() => void saver.current?.retry(), []);

  // waits for a job to finish and puts its report on screen, for uploads, reopens and re-analysis
  const followJob = useCallback(
    async (id: string, signal: AbortSignal) => {
      try {
        const last = await pollJob(() => fetchJobStatus(id, signal), {
          intervalMs: 1000,
          signal,
          onUpdate: (status) => setRun((r) => applyStatus(r, status)),
        });
        // applyStatus already put the failure on screen. a failed re-analysis still has the last good
        // report, so that carries on to be fetched and shown under the failure
        if (last.status === "failed" && !last.report_available) return;

        const next = await fetchReport(id, signal);
        // the grid still draws without the beats file, it just can't tell the bar length
        const nextBeats = await fetchBeats(id, signal).catch((err: unknown) => {
          if (isAbortError(err)) throw err;
          return null;
        });
        setReport(next);
        setBeats(nextBeats);
        setDraft(null);
        setJobId(id);
        setRun((r) => ({ ...r, busy: false }));
      } catch (err) {
        // aborted means something else took over, that run is no longer ours to touch
        if (isAbortError(err)) return;
        setRun((r) => ({
          ...r,
          busy: false,
          errorText: offlineOr(err, (detail) => detail),
          // cap at 7 so a failed report fetch lands on the done pill, not past the end
          track: { finished: Math.min(r.track.finished, 7), at: "failed" },
        }));
      } finally {
        refreshJobs();
      }
    },
    [refreshJobs],
  );

  const takeOver = useCallback((): AbortSignal => {
    runAbort.current?.abort();
    const controller = new AbortController();
    runAbort.current = controller;
    return controller.signal;
  }, []);

  const openJob = useCallback(
    (id: string, push: boolean) => {
      const signal = takeOver();
      setMatches(null);
      resetResult();
      setUrlJob(id, push);
      setRun({ ...IDLE, busy: true, track: { finished: 1, at: "waiting" } });
      void followJob(id, signal);
    },
    [takeOver, resetResult, followJob],
  );

  // a reload or back/forward lands on whatever job the url names
  useEffect(() => {
    const fromUrl = () => {
      const id = jobIdFromSearch(window.location.search);
      if (id !== null) openJob(id, false);
      else {
        runAbort.current?.abort();
        resetResult();
        setRun(IDLE);
      }
    };
    const initial = jobIdFromSearch(window.location.search);
    if (initial !== null) openJob(initial, false);
    window.addEventListener("popstate", fromUrl);
    return () => window.removeEventListener("popstate", fromUrl);
  }, [openJob, resetResult]);

  const choose = useCallback(
    (next: File) => {
      runAbort.current?.abort();
      runAbort.current = null;
      setFile(next);
      setMatches(null);
      resetResult();
      setUrlJob(null, true);
      setRun(IDLE);
    },
    [resetResult],
  );

  const upload = useCallback(async () => {
    if (file === null) return;
    const signal = takeOver();
    setMatches(null);
    resetResult();
    setRun({ ...IDLE, busy: true, progress: { fraction: 0, complete: false }, track: { finished: 0, at: "active" } });

    let id: string;
    try {
      const created = await uploadAudio(
        file,
        (fraction) => {
          if (!signal.aborted) setRun((r) => ({ ...r, progress: { fraction, complete: false } }));
        },
        signal,
      );
      id = created.job_id;
    } catch (err) {
      if (isAbortError(err)) return;
      setRun((r) => ({
        ...r,
        busy: false,
        errorText: offlineOr(err, (detail) => `upload rejected — ${detail}`),
        track: { finished: 0, at: "failed" },
      }));
      return;
    }
    setUrlJob(id, true);
    setRun((r) => ({ ...r, progress: { fraction: 1, complete: true }, track: { finished: 1, at: "waiting" } }));
    await followJob(id, signal);
  }, [file, takeOver, resetResult, followJob]);

  const analyze = useCallback(async () => {
    if (file === null) return;
    // the same file analyzed before has its edits in that job, offer it before starting over
    const sha256 = await fileSha256(file).catch(() => null);
    if (sha256 !== null) {
      const earlier = await listJobs(sha256).catch(() => []);
      if (earlier.length > 0) {
        setMatches(earlier);
        return;
      }
    }
    await upload();
  }, [file, upload]);

  const reanalyze = useCallback(async () => {
    if (jobId === null) return;
    const id = jobId;
    const signal = takeOver();
    setRun({ ...IDLE, busy: true, track: { finished: 1, at: "waiting" } });
    try {
      await reanalyzeJob(id, signal);
    } catch (err) {
      if (isAbortError(err)) return;
      setRun((r) => ({ ...r, busy: false, errorText: offlineOr(err, (detail) => `re-analysis refused — ${detail}`) }));
      return;
    }
    resetResult();
    await followJob(id, signal);
  }, [jobId, takeOver, resetResult, followJob]);

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
        draft={draft}
        selected={selected}
        saveState={saveState}
        editable={!reshaping}
        onSelect={setSelected}
        onNudge={nudge}
        onEdit={edit}
        onRetry={retrySave}
      />

      <main className="content">
        <section className="column" aria-labelledby="source-label">
          <h2 className="section-label" id="source-label">
            source
          </h2>
          <UploadPanel file={file} busy={run.busy} progress={run.progress} onChoose={choose} onAnalyze={() => void analyze()} />
          {matches !== null && (
            <ReopenPrompt matches={matches} busy={run.busy} onReopen={(id) => openJob(id, true)} onFresh={() => void upload()} />
          )}
          <StageTrack position={run.track} message={statusText} />
          {jobId !== null && report !== null && (
            <div className="reanalyze">
              <button type="button" className="btn btn--outline" disabled={run.busy} onClick={() => void reanalyze()}>
                re-analyze
              </button>
              <span className="reanalyze__hint">manual segments and edits stay</span>
            </div>
          )}
          {jobId !== null && report !== null && <ExportPanel jobId={jobId} source={report.source} disabled={run.busy} />}

          <h2 className="section-label section-label--spaced">recent</h2>
          <RecentJobs jobs={jobs} currentId={jobId} error={jobsError} onOpen={(id) => openJob(id, true)} />
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
