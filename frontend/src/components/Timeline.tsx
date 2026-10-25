import { type KeyboardEvent, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { BeatGridPlugin } from "../beatGridPlugin";
import { changeLabels, chartSetup, chartStartFor, feelLines } from "../chartSetup";
import { ClickScheduler, clickSamples } from "../clickTrack";
import { ClockPlayer } from "../clockPlayer";
import { formatDeltaMs, formatFineMs, formatMs } from "../format";
import type { SaveState } from "../tempoEdits";
import {
  type AnchorDraft,
  bands,
  meterOrDefault,
  nearestLineMs,
  segmentAt,
  type TempoGrid,
  tempoGrid,
} from "../tempoMap";
import { readPalette } from "../theme";
import {
  edgeScrollSpeed,
  scrollKeeping,
  stepZoom,
  type VisibleWindow,
  visibleWindow,
  wheelScrollPx,
  wheelZoom,
  zoomLabel,
} from "../timelineNav";
import type { TempoEditOp } from "../types/api";
import type { BeatsFile } from "../types/beats";
import type { TimingReport } from "../types/timingReport";
import type { PcmAudio } from "../wav";
import { ChartSetup } from "./ChartSetup";
import { Loupe } from "./Loupe";
import { MeterControl } from "./MeterControl";
import { Overview } from "./Overview";
import { SegmentControl } from "./SegmentControl";
import { SuggestionList } from "./SuggestionList";

interface Props {
  audioUrl: string | null;
  report: TimingReport | null;
  beats: BeatsFile | null;
  // a nudged anchor the server doesn't have yet
  draft: AnchorDraft | null;
  selected: number;
  saveState: SaveState;
  // false while a split, merge or match is out, the indices on screen are about to change
  editable: boolean;
  onSelect: (segment: number) => void;
  onNudge: (steps: number) => void;
  onEdit: (op: TempoEditOp) => void;
  onRetry: () => void;
  // the measure the music starts in, 1 leaves measure 0 as a bar of lead-in
  firstMeasure: number;
  onFirstMeasure: (measure: number) => void;
}

type AudioState =
  | { kind: "none" }
  | { kind: "loading" }
  // the wav at its own rate for the zoomed view, see ClockPlayer.samplesForView
  | { kind: "ready"; pcm: PcmAudio | null }
  | { kind: "failed"; message: string };

const LOUPE_SPANS_MS = [40, 120, 400];
// a pointer has to move this far before a press on the waveform is a drag and not a click
const DRAG_START_PX = 3;

const StableLoupe = memo(Loupe);

function clickBuffer(context: AudioContext, accent: boolean): AudioBuffer {
  const samples = clickSamples(context.sampleRate, accent);
  const buffer = context.createBuffer(1, samples.length, context.sampleRate);
  buffer.copyToChannel(samples, 0);
  return buffer;
}

function nearest(values: number[], target: number): number | null {
  let best: number | null = null;
  for (const v of values) if (best === null || Math.abs(v - target) < Math.abs(best - target)) best = v;
  return best;
}

export function Timeline(props: Props) {
  const { audioUrl, report, beats, draft, selected, saveState, editable, onSelect, onNudge, onEdit, onRetry } = props;
  const { firstMeasure, onFirstMeasure } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const gridRef = useRef<BeatGridPlugin | null>(null);
  const clicksRef = useRef<ClickScheduler | null>(null);
  const [audio, setAudio] = useState<AudioState>({ kind: "none" });
  const [playing, setPlaying] = useState(false);
  const [clickTrack, setClickTrack] = useState(false);
  const [currentMs, setCurrentMs] = useState(0);
  // px per second, 0 is the whole song fitted to the view
  const [zoom, setZoom] = useState(0);
  const [view, setView] = useState<VisibleWindow | null>(null);
  const [overview, setOverview] = useState<Float32Array | null>(null);
  const [span, setSpan] = useState(1);
  const [centerMs, setCenterMs] = useState<number | null>(null);
  const palette = useMemo(readPalette, []);
  const [latency, setLatency] = useState<{ seconds: number; output: boolean; base: boolean } | null>(null);
  const [bpmDecimals, setBpmDecimals] = useState(2);
  const [setupRow, setSetupRow] = useState<number | null>(null);

  const [suggestion, setSuggestion] = useState<number | null>(null);
  const [feel, setFeel] = useState<number | null>(null);

  const tempoMap = report?.tempo_map ?? null;
  const durationMs = report?.source.duration_ms ?? 0;
  const meterMap = useMemo(
    () => (report !== null ? meterOrDefault(report.meter_map, report.tempo_map) : []),
    [report],
  );
  const grid = useMemo<TempoGrid | null>(
    () =>
      tempoMap !== null && report !== null
        ? tempoGrid(tempoMap, meterMap, durationMs, draft, chartStartFor(report, beats, firstMeasure))
        : null,
    [tempoMap, meterMap, durationMs, draft, report, beats, firstMeasure],
  );
  const suggestions = report?.notation_suggestions;
  // only the open ones go on the timeline, the decided ones are history
  const marks = useMemo(
    () =>
      (suggestions ?? []).flatMap((s, i) =>
        s.status === "open" ? [{ startMs: s.start_ms, endMs: s.end_ms, selected: i === suggestion }] : [],
      ),
    [suggestions, suggestion],
  );
  const segmentBands = useMemo(() => (tempoMap !== null ? bands(tempoMap) : []), [tempoMap]);
  const offbeatRuns = report?.offbeat_runs;
  const offbeatShades = useMemo(
    () => (offbeatRuns ?? []).map((run) => ({ startMs: run.start_ms, endMs: run.end_ms })),
    [offbeatRuns],
  );
  const spans = report?.confidence_spans;
  // only under auto segments, an edited segment has a grid the spans weren't measured on
  const lowShades = useMemo(
    () =>
      (spans ?? []).flatMap((s) => {
        const seg = tempoMap?.[segmentAt(tempoMap, (s.start_ms + s.end_ms) / 2)];
        return s.low && seg?.source === "auto" ? [{ startMs: s.start_ms, endMs: s.end_ms }] : [];
      }),
    [spans, tempoMap],
  );
  const source = report?.source ?? null;
  const setup = useMemo(
    () => (grid !== null && tempoMap !== null && source !== null ? chartSetup(grid, tempoMap, meterMap, source) : null),
    [grid, tempoMap, meterMap, source],
  );
  const changes = useMemo(
    () =>
      setup === null
        ? []
        : changeLabels(setup, bpmDecimals).map((label, i, all) => {
            const next = all[i + 1]?.row ?? Infinity;
            return { timeMs: label.timeMs, text: label.text, selected: setupRow !== null && label.row <= setupRow && setupRow < next };
          }),
    [setup, bpmDecimals, setupRow],
  );
  const subdivisions = useMemo(() => report?.subdivision_sections ?? [], [report]);
  // the bpm each section's notes are written at now, an edit can have halved or doubled it
  const feelBpm = useMemo(
    () => subdivisions.map((d) => (tempoMap !== null ? (tempoMap[segmentAt(tempoMap, d.start_ms)]?.bpm ?? d.grid_bpm) : d.grid_bpm)),
    [subdivisions, tempoMap],
  );
  const feelRows = useMemo(
    () => (grid !== null ? feelLines(grid, subdivisions, feelBpm) : []),
    [grid, subdivisions, feelBpm],
  );
  const trackedMs = useMemo(() => beats?.beats.map((b) => b.time_ms) ?? [], [beats]);
  // the loupe opens on the first tracked downbeat, that's the first segment's anchor
  const firstDownbeatMs = beats?.beats.find((b) => b.is_downbeat)?.time_ms ?? null;

  // the latest values for wavesurfer callbacks, which only get bound once per file
  const live = useRef({ grid, trackedMs, tempoMap, onSelect });
  live.current = { grid, trackedMs, tempoMap, onSelect };
  const zoomRef = useRef(0);

  // a click, the end of a drag or a jump picks the segment there and puts the nearest attack in
  // the loupe, falling back to the grid if nothing was tracked there
  const pick = useCallback((ms: number) => {
    const { grid: g, trackedMs: tracked, tempoMap: map, onSelect: select } = live.current;
    if (map !== null) select(segmentAt(map, ms));
    setCenterMs(nearest(tracked, ms) ?? (g ? nearestLineMs(g, ms) : null) ?? ms);
  }, []);

  // zooms to pxPerS keeping timeS at offsetPx from the view's left edge
  const applyZoom = useCallback((pxPerS: number, timeS: number, offsetPx: number) => {
    const ws = wsRef.current;
    if (ws === null) return;
    ws.zoom(pxPerS);
    zoomRef.current = pxPerS;
    setZoom(pxPerS);
    if (pxPerS > 0) ws.setScroll(scrollKeeping(timeS, pxPerS, offsetPx));
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (audioUrl === null || container === null) {
      setAudio({ kind: "none" });
      return;
    }
    const plugin = BeatGridPlugin.create({
      grid: null,
      bands: [],
      selected: null,
      marks: { offbeat: [], suggestions: [], lowConfidence: [], changes: [] },
      colors: {
        beat: palette.inkFaint,
        bar: palette.mint,
        label: palette.ink,
        labelBg: palette.bgSunk,
        band: palette.ink,
        selected: palette.accent,
        bandLabel: palette.inkSoft,
        offbeat: palette.inkSoft,
        suggestion: palette.inkSoft,
        change: palette.ink,
        lowConfidence: palette.danger,
      },
      labelFont: `500 12px ${palette.fontMono}`,
    });
    // the music and the click track share this context, so a click and the beat it marks are
    // started on one clock. see clockPlayer.ts and decisions.md (click track)
    const context = new AudioContext();
    const player = new ClockPlayer(context);
    const clicks = new ClickScheduler(player, context.destination, {
      plain: clickBuffer(context, false),
      accent: clickBuffer(context, true),
    });
    const ws = WaveSurfer.create({
      container,
      url: audioUrl,
      media: player as unknown as HTMLMediaElement,
      height: "auto",
      waveColor: palette.inkFaint,
      progressColor: palette.inkSoft,
      cursorColor: palette.accent,
      cursorWidth: 2,
      normalize: true,
      minPxPerSec: 0,
      fillParent: true,
      autoScroll: true,
      autoCenter: true,
      // dragging is done here, so a drag held at an edge keeps scrolling. wavesurfer's own only
      // nudges the view when the pointer moves, so it stopped as soon as the hand did
      dragToSeek: false,
      plugins: [plugin],
    });
    wsRef.current = ws;
    gridRef.current = plugin;
    clicksRef.current = clicks;
    setAudio({ kind: "loading" });
    setPlaying(false);
    setCurrentMs(0);
    setZoom(0);
    zoomRef.current = 0;
    setView(null);
    setOverview(null);

    const durationMs = () => ws.getDuration() * 1000;
    const updateView = () => setView(visibleWindow(ws.getScroll(), ws.getWidth(), ws.getWrapper().clientWidth, durationMs()));
    // the time under a pointer, kept inside the view so a drag past the edge doesn't jump the scroll
    const timeAtX = (clientX: number) => {
      const view = container.getBoundingClientRect();
      const x = Math.min(view.right - 1, Math.max(view.left, clientX));
      const rect = ws.getWrapper().getBoundingClientRect();
      const fraction = rect.width > 0 ? (x - rect.left) / rect.width : 0;
      return Math.min(1, Math.max(0, fraction)) * durationMs();
    };
    let ready = false;
    let drag: { id: number; startX: number; x: number; active: boolean } | null = null;
    let frame = 0;
    let last = 0;

    const tick = (now: number) => {
      if (drag === null || !drag.active) return;
      const dt = last > 0 ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      const rect = container.getBoundingClientRect();
      const speed = edgeScrollSpeed(drag.x, rect.left, rect.right);
      if (speed !== 0 && dt > 0) {
        ws.setScroll(ws.getScroll() + speed * dt);
        ws.setTime(timeAtX(drag.x) / 1000);
      }
      frame = requestAnimationFrame(tick);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!ready || event.button !== 0) return;
      drag = { id: event.pointerId, startX: event.clientX, x: event.clientX, active: false };
    };
    const onPointerMove = (event: PointerEvent) => {
      if (drag === null || event.pointerId !== drag.id) return;
      drag.x = event.clientX;
      if (!drag.active && Math.abs(event.clientX - drag.startX) > DRAG_START_PX) {
        drag.active = true;
        // captured only once it's a drag, a plain click still goes to wavesurfer as a seek
        container.setPointerCapture(event.pointerId);
        last = 0;
        frame = requestAnimationFrame(tick);
      }
      if (drag.active) ws.setTime(timeAtX(event.clientX) / 1000);
    };
    const onPointerUp = (event: PointerEvent) => {
      if (drag === null || event.pointerId !== drag.id) return;
      if (drag.active) pick(timeAtX(drag.x));
      drag = null;
      cancelAnimationFrame(frame);
    };
    const onWheel = (event: WheelEvent) => {
      if (!ready) return;
      if (event.ctrlKey) {
        // ctrl+wheel is the browser's page zoom otherwise, and a trackpad pinch sends it too
        event.preventDefault();
        const rect = container.getBoundingClientRect();
        const next = wheelZoom(zoomRef.current, ws.getWidth() / ws.getDuration(), event);
        applyZoom(next, timeAtX(event.clientX) / 1000, event.clientX - rect.left);
        return;
      }
      // at fit there's nothing to scroll sideways, the page gets the wheel
      if (zoomRef.current === 0) return;
      event.preventDefault();
      ws.setScroll(ws.getScroll() + wheelScrollPx(event, ws.getWidth()));
    };
    container.addEventListener("pointerdown", onPointerDown);
    container.addEventListener("pointermove", onPointerMove);
    container.addEventListener("pointerup", onPointerUp);
    container.addEventListener("pointercancel", onPointerUp);
    container.addEventListener("wheel", onWheel, { passive: false });

    const subscriptions = [
      ws.on("ready", () => {
        ready = true;
        setAudio({ kind: "ready", pcm: player.samplesForView() });
        setLatency(player.latencyInfo());
        setOverview(ws.getDecodedData()?.getChannelData(0) ?? null);
        updateView();
      }),
      ws.on("scroll", updateView),
      ws.on("zoom", updateView),
      ws.on("resize", updateView),
      ws.on("error", (err) => setAudio({ kind: "failed", message: err.message || "could not decode the audio" })),
      ws.on("timeupdate", (t) => setCurrentMs(t * 1000)),
      ws.on("play", () => {
        setPlaying(true);
        // outputLatency settles once the output is running, and changes with the device
        setLatency(player.latencyInfo());
      }),
      ws.on("pause", () => setPlaying(false)),
      ws.on("finish", () => setPlaying(false)),
      ws.on("interaction", (t) => pick(t * 1000)),
    ];
    return () => {
      for (const unsubscribe of subscriptions) unsubscribe();
      cancelAnimationFrame(frame);
      container.removeEventListener("pointerdown", onPointerDown);
      container.removeEventListener("pointermove", onPointerMove);
      container.removeEventListener("pointerup", onPointerUp);
      container.removeEventListener("pointercancel", onPointerUp);
      container.removeEventListener("wheel", onWheel);
      clicks.dispose();
      ws.destroy();
      // wavesurfer leaves a media element it was handed alone
      player.destroy();
      wsRef.current = null;
      gridRef.current = null;
      clicksRef.current = null;
    };
  }, [audioUrl, palette, pick, applyZoom]);

  // the click track follows the grid on screen, a nudged anchor included
  useEffect(() => {
    clicksRef.current?.setGrid(grid);
  }, [grid, audio.kind]);

  useEffect(() => {
    clicksRef.current?.setEnabled(clickTrack);
  }, [clickTrack, audio.kind]);

  useEffect(() => {
    gridRef.current?.setMap(grid, segmentBands, tempoMap !== null && tempoMap.length > 1 ? selected : null, {
      offbeat: offbeatShades,
      suggestions: marks,
      lowConfidence: lowShades,
      changes,
    });
  }, [grid, segmentBands, selected, tempoMap, offbeatShades, marks, lowShades, changes, audio.kind]);

  // a new report can renumber the suggestions, the pick doesn't carry over
  useEffect(() => setSuggestion(null), [suggestions]);
  useEffect(() => setFeel(null), [subdivisions]);

  const firstAnchorMs = tempoMap?.[0]?.anchor_ms ?? null;
  useEffect(() => {
    if (audio.kind === "ready") setCenterMs((c) => c ?? firstDownbeatMs ?? firstAnchorMs);
    if (audio.kind === "none") setCenterMs(null);
    // the anchor is left out on purpose, an anchor edit must not move the loupe
  }, [audio.kind, firstDownbeatMs]);

  const ready = audio.kind === "ready";
  const spanMs = LOUPE_SPANS_MS[span] ?? 120;
  const gridAtCenter = grid !== null && centerMs !== null ? nearestLineMs(grid, centerMs) : null;
  const segment = tempoMap?.[selected] ?? null;
  const anchorMs = segment === null ? null : draft !== null && draft.segment === selected ? draft.anchorMs : segment.anchor_ms;
  // anchor here and split here act on a tracked beat, not on wherever the loupe was left
  const beatMs = centerMs !== null && trackedMs.includes(centerMs) ? centerMs : null;
  // the meter under the zoomed view, or under the selected segment's start before anything was clicked
  const meterIndex = segmentAt(meterMap, centerMs ?? segment?.start_ms ?? 0);
  const meter = meterMap[meterIndex] ?? null;

  function goToSuggestion(index: number) {
    const s = suggestions?.[index];
    if (s === undefined) return;
    setSuggestion(index);
    if (tempoMap !== null) onSelect(segmentAt(tempoMap, s.start_ms));
    // the playhead and the zoomed view jump to its start, the waveform scrolls along with the playhead
    setCenterMs(nearest(trackedMs, s.start_ms) ?? s.start_ms);
    if (ready) wsRef.current?.setTime(s.start_ms / 1000);
  }

  function goToFeel(index: number) {
    const s = subdivisions[index];
    if (s === undefined) return;
    setFeel(index);
    if (tempoMap !== null) onSelect(segmentAt(tempoMap, s.start_ms));
    setCenterMs(nearest(trackedMs, s.start_ms) ?? s.start_ms);
    if (ready) wsRef.current?.setTime(s.start_ms / 1000);
  }

  function goToChange(row: number) {
    const r = setup?.rows[row];
    if (r === undefined) return;
    setSetupRow(row);
    if (tempoMap !== null) onSelect(segmentAt(tempoMap, r.timeMs));
    setCenterMs(r.timeMs);
    if (ready) wsRef.current?.setTime(Math.max(0, r.timeMs) / 1000);
  }

  // the -/+ buttons keep the playhead where it is on screen, or bring it to the middle
  function zoomBy(direction: 1 | -1) {
    const ws = wsRef.current;
    if (ws === null || !ready) return;
    const next = stepZoom(zoom, ws.getWidth() / ws.getDuration(), direction);
    const t = ws.getCurrentTime();
    const onScreen = (t / ws.getDuration()) * ws.getWrapper().clientWidth - ws.getScroll();
    const offset = onScreen >= 0 && onScreen <= ws.getWidth() ? onScreen : ws.getWidth() / 2;
    applyZoom(next, t, offset);
  }

  // from the overview: the timeline's view moves there. with the whole song in view already
  // there's nothing to move, so the playhead goes there instead
  function jumpTo(ms: number) {
    const ws = wsRef.current;
    if (ws === null || !ready) return;
    if (zoom === 0) {
      ws.setTime(ms / 1000);
      setCenterMs(nearest(trackedMs, ms) ?? ms);
      return;
    }
    ws.setScroll(scrollKeeping(ms / 1000, zoom, ws.getWidth() / 2));
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!ready) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      if (!editable) return;
      onNudge(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === " " && event.target === sectionRef.current) {
      // only on the waveform itself, space on a focused button already clicks it
      event.preventDefault();
      void wsRef.current?.playPause();
    }
  }

  let placeholder: string | null = null;
  if (audio.kind === "loading") placeholder = "loading audio";
  else if (audio.kind === "failed") placeholder = `audio failed to load — ${audio.message}`;

  return (
    <div className="editor" onKeyDown={onKeyDown}>
      <div className="timeline__head">
        <p className="timeline__label">whole song</p>
        {report !== null && (
          <p className="timeline__file mono" title={report.source.filename}>
            {report.source.filename}
          </p>
        )}
        <div className="timeline__zoom" role="group" aria-label="zoom">
          <button
            type="button"
            className="btn btn--step"
            disabled={!ready || zoom === 0}
            onClick={() => zoomBy(-1)}
            aria-label="zoom out"
            title="zoom out, ctrl+wheel over the timeline zooms around the mouse"
          >
            −
          </button>
          <span className="transport__level mono" title="how many px one second of audio takes on the timeline">
            {zoomLabel(zoom)}
          </span>
          <button
            type="button"
            className="btn btn--step"
            disabled={!ready || zoom >= 2000}
            onClick={() => zoomBy(1)}
            aria-label="zoom in"
            title="zoom in, ctrl+wheel over the timeline zooms around the mouse"
          >
            +
          </button>
        </div>
      </div>
      <Overview
        samples={overview}
        durationMs={durationMs}
        view={view}
        playheadMs={currentMs}
        palette={palette}
        onJump={jumpTo}
      />
      <section
        ref={sectionRef}
        className="timeline"
        data-tour="timeline"
        aria-label="timeline, arrow keys move the selected segment's anchor by 1 ms, space plays"
        title="click to move the playhead, drag near an edge to keep scrolling, the wheel scrolls sideways, ctrl+wheel zooms"
        tabIndex={ready ? 0 : -1}
      >
        <div className="timeline__wave" ref={containerRef} />
        {placeholder !== null && (
          <div className="timeline__body">
            <p className="timeline__placeholder" data-failed={audio.kind === "failed"}>
              {placeholder}
            </p>
          </div>
        )}
      </section>

      {report !== null && (
        <div className="detail">
          <div className="transport">
            <button
              type="button"
              className="btn btn--outline"
              disabled={!ready}
              title="play or pause, space does the same while the timeline has focus"
              onClick={() => void wsRef.current?.playPause()}
            >
              {playing ? "pause" : "play"}
            </button>
            <button
              type="button"
              className="btn btn--outline btn--toggle"
              aria-pressed={clickTrack}
              disabled={!ready}
              title="a click on every beat of the grid, a higher one on every bar line"
              onClick={() => setClickTrack((on) => !on)}
            >
              click track
            </button>
            <p className="transport__time mono">
              {formatMs(currentMs)}
              {report !== null && <span className="transport__total"> / {formatMs(report.source.duration_ms)}</span>}
            </p>
            {ready && latency !== null && (
              <p className="transport__latency" title="the playhead is drawn this much behind the audio, the sound and the clicks aren't moved">
                {latency.output || latency.base ? (
                  <>
                    playhead <span className="mono">−{formatMs(latency.seconds * 1000)}</span>{" "}
                    {latency.output ? "output latency" : "base latency only, no output latency reported"}
                  </>
                ) : (
                  "the browser reports no output latency, the playhead isn't compensated"
                )}
              </p>
            )}
          </div>

          <div className="detail__loupe" data-tour="loupe">
            <p className="detail__label">
              zoomed view around the playhead <span className="mono">±{spanMs / 2} ms</span>
            </p>
            <StableLoupe
              audio={audio.kind === "ready" ? audio.pcm : null}
              grid={grid}
              centerMs={ready ? centerMs : null}
              spanMs={spanMs}
              trackedMs={trackedMs}
              palette={palette}
            />
            <div className="loupe__caption">
              <span className="mono">−{spanMs / 2} ms</span>
              <span className="loupe__readout mono">
                {centerMs !== null && gridAtCenter !== null && ready
                  ? `tracked ${formatFineMs(centerMs)} · grid ${formatDeltaMs(gridAtCenter - centerMs)}`
                  : ""}
              </span>
              <span className="mono">+{spanMs / 2} ms</span>
            </div>
            <div className="loupe__spans" role="group" aria-label="zoomed view width">
              {LOUPE_SPANS_MS.map((ms, i) => (
                <button
                  key={ms}
                  type="button"
                  className="btn btn--chip mono"
                  aria-pressed={span === i}
                  title={`show ${ms} ms around the playhead`}
                  onClick={() => setSpan(i)}
                >
                  {ms} ms
                </button>
              ))}
            </div>
            <div className="detail__under">
              {/* under the zoomed view, it acts on the meter at the beat in there */}
              {meter !== null && (
                <MeterControl
                  meter={meter}
                  index={meterIndex}
                  count={meterMap.length}
                  splitAtMs={beatMs ?? gridAtCenter}
                  disabled={!ready || !editable}
                  onEdit={onEdit}
                />
              )}
              <SuggestionList
                suggestions={suggestions ?? []}
                selected={suggestion}
                feels={subdivisions}
                feelBpm={feelBpm}
                selectedFeel={feel}
                disabled={!ready || !editable}
                onSelect={goToSuggestion}
                onSelectFeel={goToFeel}
                onEdit={onEdit}
              />
            </div>
          </div>

          {segment !== null && tempoMap !== null && anchorMs !== null && (
            <SegmentControl
              segment={segment}
              index={selected}
              count={tempoMap.length}
              anchorMs={anchorMs}
              beatMs={beatMs}
              saveState={saveState}
              offbeatRuns={(offbeatRuns ?? []).filter((run) => run.end_ms >= segment.start_ms && run.start_ms < segment.end_ms)}
              crossCheck={
                // the check was made on the analysis' segments, an edited one isn't the same stretch any more
                segment.source === "auto"
                  ? (report.cross_check?.segments.find((c) => c.start_ms === segment.start_ms && c.end_ms === segment.end_ms) ?? null)
                  : null
              }
              maxDisagreementMs={report.cross_check?.max_disagreement_ms ?? null}
              disabled={!ready || !editable}
              onNudge={onNudge}
              onEdit={onEdit}
              onRetry={onRetry}
            />
          )}

          {setup !== null && (
            <ChartSetup
              setup={setup}
              filename={report.source.filename}
              bpmDecimals={bpmDecimals}
              onBpmDecimals={setBpmDecimals}
              selected={setupRow}
              onSelect={goToChange}
              onFirstMeasure={onFirstMeasure}
              feelLines={feelRows}
            />
          )}
        </div>
      )}
    </div>
  );
}

