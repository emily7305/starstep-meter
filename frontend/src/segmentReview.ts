// a manual segment next to what the latest analysis has under it. re-analysis keeps manual
// segments as they are, so a fix the analysis got since never reaches them unless this says so

import { formatBpm, formatMs } from "./format";
import { periodMs } from "./grid";
import type { MeterSegment, TempoSegment, TimingReport } from "./types/timingReport";

// x2 and /2 up to three times, the same as the backend's NOTATION_SCALES
const SCALES = [0.125, 0.25, 0.5, 1, 2, 4, 8];
// a bpm typed by hand this close to a power of two of the analysis' counts as that notation
// choice, the backend's NOTATION_MATCH
const NOTATION_MATCH = 0.01;
// closer than this the first beats are the same one, reports keep 3 decimals
const SAME_ANCHOR_MS = 0.5;

export function notationScaleOf(ratio: number, tolerance = NOTATION_MATCH): number | null {
  return SCALES.find((scale) => Math.abs(ratio / scale - 1) <= tolerance) ?? null;
}

// x2 and /2 on an auto segment as the band label and the panel show them, null for 1
export function notationText(scale: number): string | null {
  if (scale === 1) return null;
  return scale > 1 ? `×${scale}` : `÷${Math.round(1 / scale)}`;
}

export interface SegmentReview {
  // where the analysis puts the first beat against this segment's, positive for later, within half a bar.
  // null when it's the same beat
  shiftMs: number | null;
  // the same in beats of this segment's grid
  shiftBeats: number | null;
  // the analysis' bpm with this segment's x2 or /2 on it, null when the bpm is the same
  analysisBpm: number | null;
  // the time signatures over the segment, here and in the analysis, null when they're the same
  meter: { here: string; analysis: string } | null;
}

function overlap(a: { start_ms: number; end_ms: number }, start: number, end: number): number {
  return Math.min(a.end_ms, end) - Math.max(a.start_ms, start);
}

function signatures(meter: MeterSegment[], start: number, end: number): string {
  const inside = meter.filter((m) => overlap(m, start, end) > 1);
  const text = inside.map((m) => `${m.numerator}/${m.denominator}`);
  // the same signature twice in a row is a restart of the bars, it reads as one
  return text.filter((t, i) => t !== text[i - 1]).join(", then ") || "4/4";
}

function barBeatsAt(meter: MeterSegment[], timeMs: number): number {
  const m = meter.find((x) => x.start_ms <= timeMs + 1 && timeMs < x.end_ms) ?? meter[0];
  return m === undefined ? 4 : (m.numerator * 4) / m.denominator;
}

export function reviewSegment(report: TimingReport, index: number): SegmentReview | null {
  const seg = report.tempo_map[index];
  const auto = report.auto_result;
  if (seg === undefined || seg.source !== "manual" || auto === null) return null;
  // the analysis' segment under most of this one
  let under: TempoSegment | undefined;
  let best = 0;
  for (const a of auto.tempo_map) {
    const shared = overlap(a, seg.start_ms, seg.end_ms);
    if (shared > best) [under, best] = [a, shared];
  }
  if (under === undefined) return null;

  const scale = notationScaleOf(seg.bpm / under.bpm);
  const scaledBpm = under.bpm * (scale ?? 1);
  const analysisBpm = scale === null ? scaledBpm : null;

  // the first beats compared within one bar of this segment's grid, a whole bar off is the same bar line
  const period = periodMs(seg.bpm);
  const bar = barBeatsAt(report.meter_map, seg.start_ms) * period;
  const raw = under.anchor_ms - seg.anchor_ms;
  const within = raw - Math.round(raw / bar) * bar;
  const shiftMs = Math.abs(within) < SAME_ANCHOR_MS ? null : within;

  const here = signatures(report.meter_map, seg.start_ms, seg.end_ms);
  const analysis = signatures(auto.meter_map, seg.start_ms, seg.end_ms);
  const meter = here === analysis ? null : { here, analysis };

  if (shiftMs === null && analysisBpm === null && meter === null) return null;
  return { shiftMs, shiftBeats: shiftMs === null ? null : shiftMs / period, analysisBpm, meter };
}

// a nudge of a few ms is a tiny part of a beat, saying 0.01 beats adds nothing
function beatsText(beats: number): string | null {
  const n = Math.abs(beats);
  const rounded = Math.round(n);
  if (rounded >= 1 && Math.abs(n - rounded) < 0.02) return rounded === 1 ? "1 beat" : `${rounded} beats`;
  return n < 0.05 ? null : `${n.toFixed(2)} beats`;
}

// "this segment is manual; the new analysis would put its first beat 411.0 ms (1 beat) earlier"
export function reviewText(review: SegmentReview): string {
  const parts: string[] = [];
  if (review.shiftMs !== null && review.shiftBeats !== null) {
    const way = review.shiftMs > 0 ? "later" : "earlier";
    const beats = beatsText(review.shiftBeats);
    parts.push(`would put its first beat ${formatMs(Math.abs(review.shiftMs))}${beats === null ? "" : ` (${beats})`} ${way}`);
  }
  if (review.analysisBpm !== null) parts.push(`has it at ${formatBpm(review.analysisBpm)}`);
  if (review.meter !== null) parts.push(`has ${review.meter.analysis} where this has ${review.meter.here}`);
  const joined = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}` : (parts[0] ?? "");
  return `this segment is manual; the new analysis ${joined}`;
}
