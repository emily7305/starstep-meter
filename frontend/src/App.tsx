import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  audioUrl,
  cancelJob,
  createDemo,
  deleteJob,
  fetchBeats,
  fetchHealth,
  fetchJobStatus,
  fetchReport,
  isAbortError,
  listJobs,
  patchTempo,
  reanalyzeJob,
  type ReanalyzeMode,
  uploadAudio,
} from "./api";
import { chartStartFor, storedFirstMeasure, storedOffsetSign, storeFirstMeasure, storeOffsetSign } from "./chartSetup";
import { Analyzing } from "./components/Analyzing";
import { ExportPanel } from "./components/ExportPanel";
import { Footer } from "./components/Footer";
import { HealthReadout, type Health } from "./components/HealthReadout";
import { QuickAnswer } from "./components/QuickAnswer";
import { ReanalyzeControl } from "./components/ReanalyzeControl";
import { RecentJobs } from "./components/RecentJobs";
import { ReopenPrompt } from "./components/ReopenPrompt";
import { ReportView } from "./components/ReportView";
import { StageTrack, trackFor, type TrackPosition } from "./components/StageTrack";
import { Timeline } from "./components/Timeline";
import { Tour } from "./components/Tour";
import { UploadPanel, type UploadProgress } from "./components/UploadPanel";
import { carriesFiles, isAudioName, NOT_AUDIO } from "./fileDrop";
import { ensureJapaneseFont } from "./fonts";
import { failureText, reanalysisFailureText, stageLabel } from "./format";
import { fileSha256, jobIdFromSearch, searchWithJob } from "./jobs";
import { pollJob } from "./poll";
import { EditSaver, nudged, type SaveState } from "./tempoEdits";
import { type AnchorDraft, appliedSegment, segmentAt, splitOutSegment } from "./tempoMap";
import { tourSeen } from "./tour";
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

// what runs right now, the picker is replaced by it until it's done
interface Active {
  // open: a job from the url or the recent list, only shown as running when the server says so
  kind: "upload" | "reanalysis" | "open" | "demo";
  name: string;
  startedAt: number;
  // null while the upload is still going
  jobId: string | null;
  cancelling: boolean;
}

const DEMO_LABEL = "demo click track";
// the name the backend gives the demo's job, for a demo opened before the job list is in
const DEMO_FILE = "demo click track.wav";
const RUNNING_STAGES = new Set<JobStage | null>(["queued", "decode", "trim", "beats", "snap", "tempo", "meter", "check"]);

function activeText(active: Active, run: RunState): string {
  if (active.kind === "upload" && run.progress !== null && !run.progress.complete) {
    return `uploading ${Math.round(run.progress.fraction * 100)}%`;
  }
  return run.stage !== null ? stageLabel(run.stage) : "starting";
}

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
  const [firstMeasure, setFirstMeasure] = useState(storedFirstMeasure);
  const [offsetSign, setOffsetSign] = useState(storedOffsetSign);
  const chartStart = useMemo(
    () => (report !== null ? chartStartFor(report, beats, firstMeasure) : null),
    [report, beats, firstMeasure],
  );
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
  // once per browser, the ? in the header opens it again
  const [tourOpen, setTourOpen] = useState(() => !tourSeen());
  // a file is being dragged over the page
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [active, setActive] = useState<Active | null>(null);
  // a song dropped while something runs, it waits for a yes or no
  const [dropped, setDropped] = useState<File | null>(null);
  // the picked file whose upload went through, the analyze button is only for a new one
  const [submitted, setSubmitted] = useState<File | null>(null);
  const activeRef = useRef<Active | null>(null);
  activeRef.current = active;
  const jobsRef = useRef<JobSummary[] | null>(null);
  jobsRef.current = jobs;
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
    if (op.op === "split" || op.op === "split_out" || op.op === "merge" || op.op === "match" || op.op === "reset_segment") {
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
        // a cancelled re-analysis came back to the report it had, there's no run to show
        setRun((r) => (activeRef.current?.cancelling ? IDLE : { ...r, busy: false }));
      } catch (err) {
        // aborted means something else took over, that run is no longer ours to touch
        if (isAbortError(err)) return;
        // a cancelled first analysis is deleted on the server, its job going away is the cancel landing
        if (activeRef.current?.cancelling && err instanceof ApiError && err.status === 404) {
          resetResult();
          setUrlJob(null, false);
          setRun(IDLE);
          return;
        }
        setRun((r) => ({
          ...r,
          busy: false,
          errorText: offlineOr(err, (detail) => detail),
          // cap at 7 so a failed report fetch lands on the done pill, not past the end
          track: { finished: Math.min(r.track.finished, 7), at: "failed" },
        }));
      } finally {
        refreshJobs();
        if (!signal.aborted) setActive(null);
      }
    },
    [refreshJobs, resetResult],
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
      setDropped(null);
      resetResult();
      setUrlJob(id, push);
      const known = jobsRef.current?.find((j) => j.job_id === id);
      setActive({
        kind: "open",
        name: known?.demo ? DEMO_LABEL : (known?.filename ?? "a song"),
        startedAt: Date.now(),
        jobId: id,
        cancelling: false,
      });
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
      setNotice(null);
      setFile(next);
      setMatches(null);
      resetResult();
      setUrlJob(null, true);
      setRun(IDLE);
    },
    [resetResult],
  );

  // a song dropped anywhere on the page is picked like one from the file dialog. dragenter and
  // dragleave fire for every element on the way, so they're counted
  useEffect(() => {
    let depth = 0;
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event.dataTransfer?.types)) return;
      depth += 1;
      setDragging(true);
    };
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event.dataTransfer?.types)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const over = (event: DragEvent) => {
      if (!carriesFiles(event.dataTransfer?.types)) return;
      // without this the browser opens the file itself
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event.dataTransfer?.types)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const file = event.dataTransfer?.files[0];
      if (file === undefined) return;
      if (!isAudioName(file.name)) setNotice(`${file.name}: ${NOT_AUDIO}`);
      // something is running, so it asks before throwing that away
      else if (activeRef.current !== null) setDropped(file);
      else choose(file);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [choose]);

  const upload = useCallback(async (next: File | null = file) => {
    if (next === null) return;
    const signal = takeOver();
    setMatches(null);
    resetResult();
    setActive({ kind: "upload", name: next.name, startedAt: Date.now(), jobId: null, cancelling: false });
    setRun({ ...IDLE, busy: true, progress: { fraction: 0, complete: false }, track: { finished: 0, at: "active" } });

    let id: string;
    try {
      const created = await uploadAudio(
        next,
        (fraction) => {
          if (!signal.aborted) setRun((r) => ({ ...r, progress: { fraction, complete: false } }));
        },
        signal,
      );
      id = created.job_id;
    } catch (err) {
      if (isAbortError(err)) return;
      setActive(null);
      setRun((r) => ({
        ...r,
        busy: false,
        errorText: offlineOr(err, (detail) => `upload rejected — ${detail}`),
        track: { finished: 0, at: "failed" },
      }));
      return;
    }
    setSubmitted(next);
    setActive((a) => (a === null ? a : { ...a, jobId: id }));
    setUrlJob(id, true);
    setRun((r) => ({ ...r, progress: { fraction: 1, complete: true }, track: { finished: 1, at: "waiting" } }));
    await followJob(id, signal);
  }, [file, takeOver, resetResult, followJob]);

  const analyze = useCallback(async (next: File | null = file) => {
    if (next === null) return;
    // the same file analyzed before has its edits in that job, offer it before starting over
    const sha256 = await fileSha256(next).catch(() => null);
    if (sha256 !== null) {
      const earlier = await listJobs(sha256).catch(() => []);
      if (earlier.length > 0) {
        setMatches(earlier);
        return;
      }
    }
    await upload(next);
  }, [file, upload]);

  // the report stays on screen while it runs, it's only replaced once the new one is in
  const reanalyze = useCallback(
    async (mode: ReanalyzeMode) => {
      if (jobId === null) return;
      const id = jobId;
      const signal = takeOver();
      const name = reportRef.current?.source.filename ?? "this song";
      setActive({ kind: "reanalysis", name, startedAt: Date.now(), jobId: id, cancelling: false });
      setRun({ ...IDLE, busy: true, track: { finished: 1, at: "waiting" } });
      try {
        await reanalyzeJob(id, mode, signal);
      } catch (err) {
        if (isAbortError(err)) return;
        setActive(null);
        setRun((r) => ({ ...r, busy: false, errorText: offlineOr(err, (detail) => `re-analysis refused — ${detail}`) }));
        return;
      }
      await followJob(id, signal);
    },
    [jobId, takeOver, followJob],
  );

  // stops at the next stage on the server. polling carries on until the job is gone or back to done
  const cancel = useCallback(async () => {
    const current = activeRef.current;
    if (current === null) return;
    if (current.jobId === null) {
      // still uploading, nothing on the server to stop yet
      runAbort.current?.abort();
      setActive(null);
      setRun(IDLE);
      return;
    }
    setActive({ ...current, cancelling: true });
    try {
      await cancelJob(current.jobId);
    } catch (err) {
      // a 409 means it finished in the meantime, the poll brings the result
      if (!(err instanceof ApiError && err.status === 409)) {
        setActive((a) => (a === null ? a : { ...a, cancelling: false }));
        setRun((r) => ({ ...r, errorText: offlineOr(err, (detail) => `cancel failed — ${detail}`) }));
      }
    }
  }, []);

  const demo = useCallback(async () => {
    const signal = takeOver();
    setMatches(null);
    setFile(null);
    setNotice(null);
    resetResult();
    setActive({ kind: "demo", name: DEMO_LABEL, startedAt: Date.now(), jobId: null, cancelling: false });
    setRun({ ...IDLE, busy: true, track: { finished: 1, at: "waiting" } });
    let id: string;
    try {
      id = (await createDemo(signal)).job_id;
    } catch (err) {
      if (isAbortError(err)) return;
      setActive(null);
      setRun((r) => ({ ...r, busy: false, errorText: offlineOr(err, (detail) => `demo failed — ${detail}`) }));
      return;
    }
    setActive((a) => (a === null ? a : { ...a, jobId: id }));
    setUrlJob(id, true);
    await followJob(id, signal);
  }, [takeOver, resetResult, followJob]);

  // the song dropped while something ran: that run is cancelled and the new one starts right away
  const startDropped = useCallback(() => {
    const next = dropped;
    setDropped(null);
    if (next === null) return;
    const current = activeRef.current;
    if (current?.jobId != null) void cancelJob(current.jobId).catch(() => undefined);
    setActive(null);
    choose(next);
    void analyze(next);
  }, [dropped, choose, analyze]);

  const removeJob = useCallback(
    async (id: string): Promise<string | null> => {
      try {
        await deleteJob(id);
      } catch (err) {
        return offlineOr(err, (detail) => `delete failed — ${detail}`);
      }
      // the url also counts, a job still loading has its id there before jobId is set
      if (id === jobId || id === jobIdFromSearch(window.location.search)) {
        runAbort.current?.abort();
        resetResult();
        setUrlJob(null, false);
        setRun(IDLE);
      }
      refreshJobs();
      return null;
    },
    [jobId, resetResult, refreshJobs],
  );

  let statusText = "";
  if (run.errorText !== null) statusText = run.errorText;
  else if (run.stage !== null) statusText = stageLabel(run.stage);

  // a job opened from the list or the url only counts as running once the server says it is
  const analyzing = active !== null && (active.kind !== "open" || RUNNING_STAGES.has(run.stage));
  // the file picked last, until its upload went through. after a failure it can be tried again
  const pending = file !== null && (file !== submitted || run.errorText !== null) ? file : null;
  const openDemo =
    report !== null && (jobs?.find((j) => j.job_id === jobId)?.demo === true || report.source.filename === DEMO_FILE);

  const recent = (
    <RecentJobs jobs={jobs} currentId={jobId} error={jobsError} onOpen={(id) => openJob(id, true)} onDelete={removeJob} />
  );
  const progress = (
    <>
      {matches !== null && (
        <ReopenPrompt matches={matches} busy={run.busy} onReopen={(id) => openJob(id, true)} onFresh={() => void upload()} />
      )}
      {/* the last run's pills only matter when it failed, a running one has its own block */}
      {run.errorText !== null && <StageTrack position={run.track} message={statusText} />}
    </>
  );
  const analyzingView =
    analyzing && active !== null ? (
      <Analyzing
        name={active.name}
        demo={active.kind === "demo"}
        position={run.track}
        stageText={activeText(active, run)}
        startedAt={active.startedAt}
        cancelling={active.cancelling}
        onCancel={() => void cancel()}
        dropped={dropped}
        onStartDropped={startDropped}
        onKeepRunning={() => setDropped(null)}
      />
    ) : null;

  return (
    <>
      <header className="header">
        <h1 className="wordmark">
          <StarMark />
          starstep-meter
        </h1>
        <div className="header__side">
          <HealthReadout health={health} />
          <button
            type="button"
            className="help-btn"
            aria-label="help, show the tour"
            title="show the tour again"
            onClick={() => setTourOpen(true)}
          >
            ?
          </button>
        </div>
      </header>

      {dragging && (
        <div className="dropping" aria-hidden="true">
          <p className="dropping__text">drop the song to load it</p>
        </div>
      )}

      {report === null ? (
        <main className="start">
          <section className="start__drop" aria-label={analyzing ? "analysis running" : "load a song"}>
            {analyzingView ?? (
              <UploadPanel
                file={pending}
                songOpen={false}
                variant="start"
                notice={notice}
                onChoose={choose}
                onAnalyze={() => void analyze()}
                onDemo={() => void demo()}
              >
                {progress}
              </UploadPanel>
            )}
          </section>
          <aside className="start__side" aria-labelledby="recent-label">
            <h2 className="section-label" id="recent-label">
              recent
            </h2>
            {recent}
          </aside>
        </main>
      ) : (
        <>
          {openDemo && (
            <p className="demo-note">
              demo: a click track with drums made on this machine, not a real song. choose a song to analyze your own.
            </p>
          )}
          {chartStart !== null && <QuickAnswer report={report} start={chartStart} offsetSign={offsetSign} />}

          <Timeline
            audioUrl={jobId === null ? null : audioUrl(jobId)}
            report={report}
            beats={beats}
            draft={draft}
            selected={selected}
            saveState={saveState}
            editable={!reshaping && active === null}
            onSelect={setSelected}
            onNudge={nudge}
            onEdit={edit}
            onRetry={retrySave}
            firstMeasure={firstMeasure}
            onFirstMeasure={(measure) => {
              setFirstMeasure(measure);
              storeFirstMeasure(measure);
            }}
            offsetSign={offsetSign}
            onOffsetSign={(sign) => {
              setOffsetSign(sign);
              storeOffsetSign(sign);
            }}
          />

          <main className="content">
            <section className="column" aria-labelledby="source-label">
              <h2 className="section-label" id="source-label">
                source
              </h2>
              {analyzingView ?? (
                <>
                  <UploadPanel
                    file={pending}
                    songOpen
                    variant="compact"
                    notice={notice}
                    onChoose={choose}
                    onAnalyze={() => void analyze()}
                  >
                    {progress}
                  </UploadPanel>
                  {jobId !== null && <ReanalyzeControl disabled={run.busy} onReanalyze={(mode) => void reanalyze(mode)} />}
                </>
              )}
              {jobId !== null && <ExportPanel jobId={jobId} disabled={run.busy} />}
            </section>

            <section className="column" aria-labelledby="recent-label">
              <h2 className="section-label" id="recent-label">
                recent
              </h2>
              {recent}
            </section>

            <section className="column column--report" aria-labelledby="report-label">
              <h2 className="section-label" id="report-label">
                report
              </h2>
              <ReportView report={report} beats={beats} />
            </section>
          </main>
        </>
      )}

      <Footer />
      <Tour open={tourOpen} onClose={() => setTourOpen(false)} />
    </>
  );
}
