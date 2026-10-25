// the beat grid over a whole tempo map: one grid per segment, each from its own anchor and bpm,
// and bar lines from the meter map. plain functions on top of grid.ts, no dom, so they can be
// tested on their own. the bar rule is the backend's (backend/analysis/bars.py), keep them in step

import { notationText } from "./segmentReview";
import { periodMs, timeToX, xToTime, type GridLine, type View } from "./grid";
import type { MeterSegment, NotationSuggestion, TempoSegment } from "./types/timingReport";

// a line less than this fraction of the new segment's period before a boundary belongs to
// the new segment, so a bpm change on a beat draws one line there and not two a hair apart.
// the backend refits segments with the same rule (tempo_edit.EDGE_FRACTION)
export const EDGE_FRACTION = 0.25;
// a bar line this close to a beat line is drawn as that line
const SAME_LINE_MS = 0.5;

export interface SegmentGrid {
  index: number;
  segment: TempoSegment;
  // where this segment's lines start and stop being drawn. the first runs from 0 and the
  // last to the end of the audio, like the single grid did before tempo maps
  fromMs: number;
  toMs: number;
  // the shortest bar in this segment in beats, for thinning out bar lines when zoomed out
  barBeats: number;
}

// a stretch with one tempo and one meter, and where its bars are counted from
export interface BarRegion {
  tempo: number;
  // index into the meter map, -1 where there's none and bars are 4/4 from the anchor
  meter: number;
  fromMs: number;
  toMs: number;
  refMs: number;
  barMs: number;
}

export interface BarLine {
  timeMs: number;
  // the measure number, the same one the chart setup list uses. negative before measure 0, those
  // aren't numbered on the timeline
  bar: number;
  segment: number;
  // index into TempoGrid.regions, the meter this bar was counted in
  region: number;
}

export interface TempoGrid {
  segments: SegmentGrid[];
  regions: BarRegion[];
  // every bar line from 0 to the end of the audio, numbered from the chart start
  bars: BarLine[];
  // where measure 0 starts, before 0 ms when the silence before the music is shorter than the lead-in
  measureZeroMs: number;
  // the measure the music starts in
  firstMeasure: number;
}

// where a chart starts: the bar the music starts in is firstMeasure, so with 1 measure 0 is one
// empty bar of lead-in and the offset skips whatever silence comes before it
export interface ChartStart {
  // the earlier of the trim start and the first tracked beat
  musicStartMs: number;
  firstMeasure: number;
}

export const DEFAULT_FIRST_MEASURE = 1;

export function chartStartOf(trimStartMs: number, firstBeatMs: number | null, firstMeasure = DEFAULT_FIRST_MEASURE): ChartStart {
  const musicStartMs = firstBeatMs === null ? trimStartMs : Math.min(trimStartMs, firstBeatMs);
  return { musicStartMs, firstMeasure };
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

function snapToGrid(segment: TempoSegment, timeMs: number): number {
  const p = periodMs(segment.bpm);
  return segment.anchor_ms + Math.round((timeMs - segment.anchor_ms) / p) * p;
}

export function barBeats(numerator: number, denominator: number): number {
  return (numerator * 4) / denominator;
}

// same rule as bars.regions: a meter that starts with its tempo segment counts from the anchor,
// one that starts later starts a bar right there, on the grid
export function barRegions(map: TempoSegment[], meter: MeterSegment[], durationMs: number): BarRegion[] {
  const out: BarRegion[] = [];
  map.forEach((seg, i) => {
    const p = periodMs(seg.bpm);
    const edge = EDGE_FRACTION * p;
    const next = map[i + 1];
    const lo = i === 0 ? 0 : lineCut(seg);
    const hi = next === undefined ? durationMs : lineCut(next);
    const inside = meter
      .map((m, j) => ({ m, j }))
      .filter(({ m }) => m.end_ms > seg.start_ms + edge && m.start_ms < seg.end_ms - edge);
    const first = inside[0];
    if (first === undefined || first.m.start_ms > seg.start_ms + edge) {
      const stop = first === undefined ? hi : snapToGrid(seg, first.m.start_ms) - edge;
      out.push({ tempo: i, meter: -1, fromMs: lo, toMs: stop, refMs: seg.anchor_ms, barMs: 4 * p });
    }
    inside.forEach(({ m, j }, k) => {
      const withSegment = m.start_ms <= seg.start_ms + edge;
      const ref = withSegment ? seg.anchor_ms : snapToGrid(seg, m.start_ms);
      const after = inside[k + 1];
      out.push({
        tempo: i,
        meter: j,
        fromMs: withSegment ? lo : ref - edge,
        toMs: after === undefined ? hi : snapToGrid(seg, after.m.start_ms) - edge,
        refMs: ref,
        barMs: barBeats(m.numerator, m.denominator) * p,
      });
    });
  });
  return out;
}

function barLinesOf(regions: BarRegion[]): Omit<BarLine, "bar">[] {
  const times: { timeMs: number; segment: number; region: number }[] = [];
  regions.forEach((r, region) => {
    if (!(r.barMs > 0) || r.toMs <= r.fromMs) return;
    // tiny slack so a line sitting exactly on fromMs isn't lost to float noise
    for (let k = Math.ceil((r.fromMs - r.refMs) / r.barMs - 1e-9); ; k += 1) {
      const t = r.refMs + k * r.barMs;
      if (t >= r.toMs) break;
      times.push({ timeMs: t, segment: r.tempo, region });
    }
  });
  times.sort((a, b) => a.timeMs - b.timeMs);
  return times;
}

// the bar the music starts in: the last bar line at or before it. a quarter beat of slack, the trim
// and the snap can land a few ms before an attack that's right on a bar line. a pickup has its own
// sound, so the music starts there and its bar is the one before the downbeat
function numberBars(
  lines: Omit<BarLine, "bar">[],
  regions: BarRegion[],
  periodAt: (timeMs: number) => number,
  start: ChartStart | null,
): { bars: BarLine[]; measureZeroMs: number; firstMeasure: number } {
  const first = lines[0];
  // no chart start (some tests) numbers from the first line in the audio
  if (first === undefined || start === null) {
    return { bars: lines.map((l, i) => ({ ...l, bar: i })), measureZeroMs: first?.timeMs ?? 0, firstMeasure: 0 };
  }
  const reach = start.musicStartMs + EDGE_FRACTION * periodAt(start.musicStartMs);
  let at = -1;
  lines.forEach((l, i) => {
    if (l.timeMs <= reach) at = i;
  });
  // before the first line in the audio the first region's bars carry on back past 0 ms
  const barMs0 = regions[0]?.barMs ?? 1;
  const before = at >= 0 ? 0 : Math.ceil((first.timeMs - reach) / barMs0 - 1e-9);
  const startIndex = at >= 0 ? at : -before;
  const bars = lines.map((l, i) => ({ ...l, bar: i - startIndex + start.firstMeasure }));
  const zero = bars.find((b) => b.bar === 0);
  const measureZeroMs = zero !== undefined ? zero.timeMs : first.timeMs - (start.firstMeasure - startIndex) * barMs0;
  return { bars, measureZeroMs, firstMeasure: start.firstMeasure };
}

export function tempoGrid(
  map: TempoSegment[],
  meter: MeterSegment[],
  durationMs: number,
  draft: AnchorDraft | null = null,
  start: ChartStart | null = null,
): TempoGrid {
  const segs = map.map((s, i) => (draft !== null && draft.segment === i ? { ...s, anchor_ms: draft.anchorMs } : s));
  const regions = barRegions(segs, meter, durationMs);
  const segments = segs.map((segment, index): SegmentGrid => {
    const next = segs[index + 1];
    const own = regions.filter((r) => r.tempo === index);
    const shortest = Math.min(...own.map((r) => r.barMs / periodMs(segment.bpm)));
    return {
      index,
      segment,
      fromMs: index === 0 ? 0 : lineCut(segment),
      toMs: next === undefined ? durationMs : lineCut(next),
      barBeats: Number.isFinite(shortest) && shortest > 0 ? shortest : 4,
    };
  });
  const periodAt = (timeMs: number) => periodMs((segs[segmentAt(segs, timeMs)] ?? segs[0])?.bpm ?? 120);
  return { segments, regions, ...numberBars(barLinesOf(regions), regions, periodAt, start) };
}

function barIndexAt(bars: BarLine[], timeMs: number): number {
  // the last bar line at or before timeMs, binary search since a song has a few hundred
  let lo = 0;
  let hi = bars.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const line = bars[mid];
    if (line !== undefined && line.timeMs <= timeMs + SAME_LINE_MS) {
      found = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return found;
}

export function mapLines(grid: TempoGrid, startMs: number, endMs: number): MapLine[] {
  if (endMs < startMs) return [];
  const out: MapLine[] = [];
  for (const seg of grid.segments) {
    const from = Math.max(startMs, seg.fromMs);
    // toMs is exclusive, the next segment draws the line that sits on it
    const to = Math.min(endMs, seg.toMs);
    if (to < from) continue;
    const p = periodMs(seg.segment.bpm);
    const anchor = seg.segment.anchor_ms;
    // || 0 because ceil of anything in (-1, 0) is -0, and the anchor should be index 0
    for (let index = Math.ceil((from - anchor) / p) || 0; ; index += 1) {
      const timeMs = anchor + index * p;
      if (timeMs > to || timeMs >= seg.toMs) break;
      const at = barIndexAt(grid.bars, timeMs);
      const bar = grid.bars[at];
      const isBar = bar !== undefined && Math.abs(bar.timeMs - timeMs) <= SAME_LINE_MS;
      // before the first bar line in the audio it's the bar before that one, measure 0 can start before 0 ms
      out.push({ timeMs, index, bar: bar?.bar ?? (grid.bars[0]?.bar ?? 0) - 1, isBar, segment: seg.index });
    }
  }
  // bar lines between beats, a 7/8 bar ends half a beat in
  for (const line of grid.bars) {
    if (line.timeMs < startMs || line.timeMs > endMs) continue;
    const onBeat = out.some((l) => l.isBar && Math.abs(l.timeMs - line.timeMs) <= SAME_LINE_MS);
    if (!onBeat) out.push({ timeMs: line.timeMs, index: Number.NaN, bar: line.bar, isBar: true, segment: line.segment });
  }
  return out.sort((a, b) => a.timeMs - b.timeMs);
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
// how many beats past the last bar line a time is, for "the bars would restart 1 beat in". null
// before the first bar line
export function beatsIntoBar(grid: TempoGrid, map: { start_ms: number; bpm: number }[], timeMs: number): number | null {
  const line = grid.bars.filter((b) => b.timeMs <= timeMs + 0.5).at(-1);
  const seg = map[segmentAt(map, timeMs)];
  if (line === undefined || seg === undefined) return null;
  return Math.round((timeMs - line.timeMs) / (60000 / seg.bpm));
}

export function segmentAt(map: { start_ms: number }[], timeMs: number): number {
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

// the meter map, or one 4/4 over the whole tempo map for a report from before meters, the
// backend writes the same one down on the first meter edit (meter_edit.meter_or_default)
export function meterOrDefault(meter: MeterSegment[], map: TempoSegment[]): MeterSegment[] {
  const first = map[0];
  const last = map.at(-1);
  if (meter.length > 0 || first === undefined || last === undefined) return meter;
  return [{ start_ms: first.start_ms, end_ms: last.end_ms, numerator: 4, denominator: 4, confidence: null, source: "auto" }];
}

// which segment the span of a suggestion ends up in once it's applied, to keep it selected.
// half and double split it off the segment it's in, a fold joins the neighbour on the inner side
export function appliedSegment(map: TempoSegment[], suggestion: NotationSuggestion): number {
  const i = segmentAt(map, suggestion.start_ms);
  const seg = map[i];
  if (seg === undefined) return 0;
  if (suggestion.kind === "fold") return Math.max(0, i - 1);
  return suggestion.start_ms - seg.start_ms > 1 ? i + 1 : i;
}

// which segment the kept section ends up as once it's split out, to keep it selected. the start
// is only cut when it's past half a beat from the segment's start, the same rule as the backend
export function splitOutSegment(map: TempoSegment[], segment: number, section: number): number {
  const seg = map[segment];
  const note = seg?.ratio_merged[section];
  if (seg === undefined || note === undefined) return segment;
  return note.start_ms - seg.start_ms >= 0.5 * periodMs(seg.bpm) ? segment + 1 : segment;
}

export interface Band {
  index: number;
  startMs: number;
  endMs: number;
  bpm: number;
  manual: boolean;
  // x2 or /2 on an auto segment, a notation choice
  notation: string | null;
}

export function bands(map: TempoSegment[]): Band[] {
  return map.map((s, index) => ({
    index,
    startMs: s.start_ms,
    endMs: s.end_ms,
    bpm: s.bpm,
    manual: s.source === "manual",
    notation: s.source === "auto" ? notationText(s.notation_scale) : null,
  }));
}
