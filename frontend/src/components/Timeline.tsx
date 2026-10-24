import { type KeyboardEvent, memo, useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { BeatGridPlugin } from "../beatGridPlugin";
import { formatDeltaMs, formatFineMs, formatMs } from "../format";
import { beatsPerBar, type GridParams, nearestBeatMs } from "../grid";
import type { SaveState } from "../offset";
import { readPalette } from "../theme";
import type { BeatsFile } from "../types/beats";
import type { TimingReport } from "../types/timingReport";
import { Loupe } from "./Loupe";
import { OffsetControl } from "./OffsetControl";

interface Props {
  audioUrl: string | null;
  report: TimingReport | null;
  beats: BeatsFile | null;
  offsetMs: number | null;
  autoOffsetMs: number | null;
  saveState: SaveState;
  onNudge: (steps: number) => void;
  onRetry: () => void;
}

type AudioState =
  | { kind: "none" }
  | { kind: "loading" }
  | { kind: "ready"; buffer: AudioBuffer | null }
  | { kind: "failed"; message: string };

// px per second, 0 is fit to width
const ZOOM_LEVELS = [0, 50, 100, 200, 500, 1000, 2000];
const LOUPE_SPANS_MS = [40, 120, 400];

const StableLoupe = memo(Loupe);

function nearest(values: number[], target: number): number | null {
  let best: number | null = null;
  for (const v of values) if (best === null || Math.abs(v - target) < Math.abs(best - target)) best = v;
  return best;
}

export function Timeline({ audioUrl, report, beats, offsetMs, autoOffsetMs, saveState, onNudge, onRetry }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const gridRef = useRef<BeatGridPlugin | null>(null);
  const [audio, setAudio] = useState<AudioState>({ kind: "none" });
  const [playing, setPlaying] = useState(false);
  const [currentMs, setCurrentMs] = useState(0);
  const [zoom, setZoom] = useState(0);
  const [span, setSpan] = useState(1);
  const [centerMs, setCenterMs] = useState<number | null>(null);
  const palette = useMemo(readPalette, []);

  const bpm = report?.tempo_map[0]?.bpm ?? null;
  const barLength = useMemo(() => (beats ? beatsPerBar(beats.beats) : 4), [beats]);
  const grid = useMemo<GridParams | null>(
    () => (offsetMs !== null && bpm !== null ? { offsetMs, bpm, beatsPerBar: barLength } : null),
    [offsetMs, bpm, barLength],
  );
  const trackedMs = useMemo(() => beats?.beats.map((b) => b.time_ms) ?? [], [beats]);
  // the loupe opens on the first tracked downbeat, that's the beat the offset is about
  const firstDownbeatMs = beats?.beats.find((b) => b.is_downbeat)?.time_ms ?? null;

  // the latest values for wavesurfer callbacks, which only get bound once per file
  const live = useRef({ grid, trackedMs });
  live.current = { grid, trackedMs };

  useEffect(() => {
    const container = containerRef.current;
    if (audioUrl === null || container === null) {
      setAudio({ kind: "none" });
      return;
    }
    const plugin = BeatGridPlugin.create({
      grid: null,
      colors: { beat: palette.inkFaint, bar: palette.mint, label: palette.inkSoft, labelBg: palette.bgSunk },
      labelFont: `500 10px ${palette.fontMono}`,
    });
    const ws = WaveSurfer.create({
      container,
      url: audioUrl,
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
      dragToSeek: true,
      plugins: [plugin],
    });
    wsRef.current = ws;
    gridRef.current = plugin;
    setAudio({ kind: "loading" });
    setPlaying(false);
    setCurrentMs(0);
    setZoom(0);

    const subscriptions = [
      ws.on("ready", () => setAudio({ kind: "ready", buffer: ws.getDecodedData() })),
      ws.on("error", (err) => setAudio({ kind: "failed", message: err.message || "could not decode the audio" })),
      ws.on("timeupdate", (t) => setCurrentMs(t * 1000)),
      ws.on("play", () => setPlaying(true)),
      ws.on("pause", () => setPlaying(false)),
      ws.on("finish", () => setPlaying(false)),
      ws.on("interaction", (t) => {
        // a click puts the nearest attack in the loupe, falling back to the grid if nothing was tracked there
        const ms = t * 1000;
        const { grid: g, trackedMs: tracked } = live.current;
        setCenterMs(nearest(tracked, ms) ?? (g ? nearestBeatMs(g, ms) : ms));
      }),
    ];
    return () => {
      for (const unsubscribe of subscriptions) unsubscribe();
      ws.destroy();
      wsRef.current = null;
      gridRef.current = null;
    };
  }, [audioUrl, palette]);

  useEffect(() => {
    gridRef.current?.setGrid(grid);
  }, [grid, audio.kind]);

  useEffect(() => {
    // wavesurfer throws on zoom before the audio is decoded
    if (audio.kind === "ready") wsRef.current?.zoom(ZOOM_LEVELS[zoom] ?? 0);
  }, [zoom, audio.kind]);

  useEffect(() => {
    if (audio.kind === "ready") setCenterMs((c) => c ?? firstDownbeatMs ?? offsetMs);
    if (audio.kind === "none") setCenterMs(null);
    // offsetMs left out on purpose, an offset edit must not move the loupe
  }, [audio.kind, firstDownbeatMs]);

  const ready = audio.kind === "ready";
  const spanMs = LOUPE_SPANS_MS[span] ?? 120;
  const gridAtCenter = grid !== null && centerMs !== null ? nearestBeatMs(grid, centerMs) : null;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!ready) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      onNudge(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === " " && event.target === sectionRef.current) {
      // only on the waveform itself, space on a focused button already clicks it
      event.preventDefault();
      void wsRef.current?.playPause();
    }
  }

  let placeholder: string | null = null;
  if (report === null) placeholder = "no audio loaded";
  else if (audio.kind === "loading") placeholder = "loading audio";
  else if (audio.kind === "failed") placeholder = `audio failed to load — ${audio.message}`;

  return (
    <div className="editor" onKeyDown={onKeyDown}>
      <section
        ref={sectionRef}
        className="timeline"
        aria-label="timeline, arrow keys move the beat offset by 1 ms, space plays"
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
        {report !== null && (
          <p className="timeline__file mono">
            <span className="timeline__name">{report.source.filename}</span>
          </p>
        )}
      </section>

      {report !== null && (
        <div className="detail">
          <div className="transport">
            <button
              type="button"
              className="btn btn--outline"
              disabled={!ready}
              onClick={() => void wsRef.current?.playPause()}
            >
              {playing ? "pause" : "play"}
            </button>
            <p className="transport__time mono">
              {formatMs(currentMs)}
              {report !== null && <span className="transport__total"> / {formatMs(report.source.duration_ms)}</span>}
            </p>
            <div className="transport__zoom" aria-label="zoom">
              <button
                type="button"
                className="btn btn--step"
                disabled={!ready || zoom === 0}
                onClick={() => setZoom((z) => Math.max(0, z - 1))}
                aria-label="zoom out"
              >
                −
              </button>
              <span className="transport__level mono">{zoom === 0 ? "fit" : `${ZOOM_LEVELS[zoom]} px/s`}</span>
              <button
                type="button"
                className="btn btn--step"
                disabled={!ready || zoom === ZOOM_LEVELS.length - 1}
                onClick={() => setZoom((z) => Math.min(ZOOM_LEVELS.length - 1, z + 1))}
                aria-label="zoom in"
              >
                +
              </button>
            </div>
          </div>

          <div className="detail__loupe">
            <StableLoupe
              audio={audio.kind === "ready" ? audio.buffer : null}
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
                  onClick={() => setSpan(i)}
                >
                  {ms} ms
                </button>
              ))}
            </div>
          </div>

          <OffsetControl
            offsetMs={offsetMs}
            autoMs={autoOffsetMs}
            saveState={saveState}
            disabled={!ready || offsetMs === null}
            onNudge={onNudge}
            onRetry={onRetry}
          />
        </div>
      )}
    </div>
  );
}

