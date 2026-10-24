// the beat grid over a whole tempo map: one grid per segment, each from its own anchor and bpm
// plain functions on top of grid.ts, no dom, so they can be tested on their own

import { gridLines, periodMs, timeToX, xToTime, type GridLine, type View } from "./grid";
import type { TempoSegment } from "./types/timingReport";

// a line less than this fraction of the new segment's period before a boundary belongs to
// the new segment, so a bpm change on a beat draws one line there and not two a hair apart.
// the backend refits segments with the same rule (tempo_edit.EDGE_FRACTION)
export const EDGE_FRACTION = 0.25;

export interface SegmentGrid {
  index: number;
  segment: TempoSegment;
  // where this segment's lines start and stop being drawn. the first runs from 0 and the
  // last to the end of the audio, like the single grid did before tempo maps
  fromMs: number;
  toMs: number;
  // added to floor(k / beatsPerBar) so bar numbers keep counting across segments
  barOffset: number;
}

export interface TempoGrid {
  segments: SegmentGrid[];
  beatsPerBar: number;
}

// an anchor being nudged that the server doesn't have yet
export interface AnchorDraft {
  segment: number;
  anchorMs: number;
}

export interface MapLine extends GridLine {
  segment: number;
}

export interface PlacedMapLine extends MapLine {
  x: number;
}

function lineCut(segment: TempoSegment): number {
  return segment.start_ms - EDGE_FRACTION * periodMs(segment.bpm);
}

function linesOf(seg: SegmentGrid, beatsPerBar: number, startMs: number, endMs: number): MapLine[] {
  const from = Math.max(startMs, seg.fromMs);
  // toMs is exclusive, the next segment draws the line that sits on it
  const to = Math.min(endMs, seg.toMs);
  if (to < from) return [];
  const params = { offsetMs: seg.segment.anchor_ms, bpm: seg.segment.bpm, beatsPerBar };
  const out: MapLine[] = [];
  for (const line of gridLines(params, from, to)) {
    if (line.timeMs >= seg.toMs) continue;
    out.push({ ...line, bar: line.bar + seg.barOffset, segment: seg.index });
  }
  return out;
}

export function tempoGrid(
  map: TempoSegment[],
  durationMs: number,
  beatsPerBar: number,
  draft: AnchorDraft | null = null,
): TempoGrid {
  const segs = map.map((s, i) => (draft !== null && draft.segment === i ? { ...s, anchor_ms: draft.anchorMs } : s));
  const grids: SegmentGrid[] = [];
  let nextBar = 0;
  segs.forEach((segment, index) => {
    const next = segs[index + 1];
    const seg: SegmentGrid = {
      index,
      segment,
      fromMs: index === 0 ? 0 : lineCut(segment),
      toMs: next === undefined ? durationMs : lineCut(next),
      barOffset: 0,
    };
    if (index > 0) {
      // the first bar line in this segment carries on from the last bar number before it
      const period = periodMs(segment.bpm);
      const firstK = Math.ceil((seg.fromMs - segment.anchor_ms) / period);
      const firstBarK = Math.ceil(firstK / beatsPerBar) * beatsPerBar;
      seg.barOffset = nextBar - Math.floor(firstBarK / beatsPerBar);
    }
    const lines = linesOf(seg, beatsPerBar, seg.fromMs, seg.toMs);
    const lastBarLine = [...lines].reverse().find((l) => l.isBar);
    if (lastBarLine !== undefined) nextBar = lastBarLine.bar + 1;
    grids.push(seg);
  });
  return { segments: grids, beatsPerBar };
}

export function mapLines(grid: TempoGrid, startMs: number, endMs: number): MapLine[] {
  if (endMs < startMs || grid.beatsPerBar < 1) return [];
  return grid.segments.flatMap((seg) => linesOf(seg, grid.beatsPerBar, startMs, endMs));
}

export function visibleMapLines(grid: TempoGrid, view: View): PlacedMapLine[] {
  const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
  const startMs = Math.max(0, xToTime(scrollLeftPx, durationMs, totalWidthPx));
  const endMs = Math.min(durationMs, xToTime(scrollLeftPx + viewWidthPx, durationMs, totalWidthPx));
  return mapLines(grid, startMs, endMs).map((line) => ({
    ...line,
    x: timeToX(line.timeMs, durationMs, totalWidthPx) - scrollLeftPx,
  }));
}

// the segment a time falls in by its start and end, clamped to the first and last
export function segmentAt(map: TempoSegment[], timeMs: number): number {
  if (map.length === 0) return -1;
  for (let i = map.length - 1; i >= 0; i -= 1) {
    const seg = map[i];
    if (seg !== undefined && timeMs >= seg.start_ms) return i;
  }
  return 0;
}

export function nearestLineMs(grid: TempoGrid, timeMs: number): number | null {
  // a period either side covers the slowest segment, plus the boundaries next to it
  const widest = Math.max(...grid.segments.map((s) => periodMs(s.segment.bpm)));
  let best: number | null = null;
  for (const line of mapLines(grid, timeMs - widest, timeMs + widest)) {
    if (best === null || Math.abs(line.timeMs - timeMs) < Math.abs(best - timeMs)) best = line.timeMs;
  }
  return best;
}

export interface Band {
  index: number;
  startMs: number;
  endMs: number;
  bpm: number;
  manual: boolean;
}

export function bands(map: TempoSegment[]): Band[] {
  return map.map((s, index) => ({ index, startMs: s.start_ms, endMs: s.end_ms, bpm: s.bpm, manual: s.source === "manual" }));
}
