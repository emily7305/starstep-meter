// what to type into a chart editor (MikuMikuWorld is the one checked): the music offset, then
// every bpm and time signature change by measure and beat. measures are the timeline's bar
// numbers, built from the same bar lines (tempoMap.ts), so the two can't drift apart.
//
// a chart editor counts beats, not ms: measure lengths come from the time signatures and a bpm
// change sits at a beat inside a measure. so the beat position of every bar line and change is
// counted along the tempo map from bar 0, the same way the sonolus export counts beats

import { type ChartStart, chartStartOf, DEFAULT_FIRST_MEASURE, EDGE_FRACTION, barBeats, type TempoGrid } from "./tempoMap";
import type { BeatsFile } from "./types/beats";
import { periodMs } from "./grid";
import type { AudioSource, MeterSegment, TempoSegment, TimingReport } from "./types/timingReport";

// two segments are fitted on their own, so where one hands over to the next is rarely a whole
// number of beats of the first (0.77 ms off on a 120 -> 150 click track). a bar length or a
// change this close in ms to whole beats is taken as whole, anything further is a real cut bar
// or a change between beats. 2 ms is a guess, under the 10 ms the confidence counts as on the grid
export const SAME_POSITION_MS = 2;
const DENOMINATORS = [1, 2, 4, 8, 16, 32, 64];
const MAX_FRACTION = 16;

export type ChartRow =
  | { kind: "bpm"; timeMs: number; measure: number; beat: number; bpm: number }
  | { kind: "signature"; timeMs: number; measure: number; beat: number; numerator: number; denominator: number };

export interface ChartSetup {
  // where measure 0 starts in the audio file, on ffmpeg's timeline. before 0 ms when the silence
  // before the music is shorter than the lead-in, the offset is positive then
  measureZeroMs: number;
  // the measure the music starts in, and where that is
  firstMeasure: number;
  firstMeasureMs: number;
  // the editor's offset, positive starts the song later, so it's minus where measure 0 is
  wavOffsetMs: number;
  // with the original file in an editor that plays its decoder padding (mikumikuworld does for mp3)
  originalOffsetMs: number;
  paddingMs: number;
  // the original file's extension, mp3, ogg...
  kind: string;
  rows: ChartRow[];
}

interface Change {
  timeMs: number;
  bpm: number;
  // beats from bar 0
  beat: number;
}

function firstLine(seg: TempoSegment): number {
  const p = periodMs(seg.bpm);
  return seg.anchor_ms + Math.ceil((seg.start_ms - EDGE_FRACTION * p - seg.anchor_ms) / p - 1e-9) * p;
}

// each segment's first grid line is where its tempo starts, the line the timeline draws there
function changesFrom(map: TempoSegment[], originMs: number): Change[] {
  const starts: { timeMs: number; bpm: number }[] = [];
  map.forEach((seg, i) => {
    const at = i === 0 ? -Infinity : firstLine(seg);
    const next = map[i + 1];
    // a sliver with no line of its own changes nothing, the tempo before it runs on
    if (next !== undefined && at >= next.start_ms - EDGE_FRACTION * periodMs(next.bpm)) return;
    starts.push({ timeMs: at, bpm: seg.bpm });
  });
  // the tempo in force at bar 0 starts the count there, anything before bar 0 isn't in the chart
  const active = starts.filter((s) => s.timeMs <= originMs + 1e-6).at(-1) ?? starts[0];
  if (active === undefined) return [];
  const out: Change[] = [{ timeMs: originMs, bpm: active.bpm, beat: 0 }];
  for (const s of starts) {
    if (s.timeMs <= originMs + 1e-6) continue;
    const prev = out[out.length - 1] as Change;
    out.push({ timeMs: s.timeMs, bpm: s.bpm, beat: prev.beat + (s.timeMs - prev.timeMs) / periodMs(prev.bpm) });
  }
  return out;
}

function beatAt(changes: Change[], timeMs: number): number {
  let c = changes[0] as Change;
  for (const next of changes) if (next.timeMs <= timeMs + 1e-6) c = next;
  return c.beat + (timeMs - c.timeMs) / periodMs(c.bpm);
}

// a cut bar written as n/d, its own denominator first so half a 4/4 bar reads 2/4
function signatureOf(lengthBeats: number, preferred: number): [number, number] {
  for (const d of [preferred, ...DENOMINATORS]) {
    const n = Math.round((lengthBeats * d) / 4);
    if (n >= 1 && Math.abs((n * 4) / d - lengthBeats) < 1e-4) return [n, d];
  }
  // todo: only happens next to a bpm change on a fractional beat, the nearest 64ths is all an editor takes
  return [Math.max(1, Math.round(lengthBeats * 16)), 64];
}

export function decoderPaddingMs(source: AudioSource): number {
  return (source.decoder_padding_samples / source.sample_rate) * 1000;
}

// whole beats when within SAME_POSITION_MS of them at this tempo
function snapBeats(beats: number, bpm: number): number {
  const whole = Math.round(beats);
  return Math.abs(beats - whole) * periodMs(bpm) < SAME_POSITION_MS ? whole : beats;
}

interface Measure {
  timeMs: number;
  region: number;
}

// measure 0 on, the ones before 0 ms worked out from the first region's bars like the timeline does
function measuresOf(grid: TempoGrid): Measure[] {
  const listed = grid.bars.filter((b) => b.bar >= 0);
  const first = listed[0];
  if (first === undefined) return [];
  const barMs0 = grid.regions[0]?.barMs ?? 1;
  const before: Measure[] = [];
  for (let m = 0; m < first.bar; m += 1) before.push({ timeMs: first.timeMs - (first.bar - m) * barMs0, region: 0 });
  return [...before, ...listed.map((b) => ({ timeMs: b.timeMs, region: b.region }))];
}

export function chartSetup(grid: TempoGrid, map: TempoSegment[], meter: MeterSegment[], source: AudioSource): ChartSetup | null {
  const measures = measuresOf(grid);
  const zero = measures[0];
  if (zero === undefined || map.length === 0) return null;
  const changes = changesFrom(map, zero.timeMs);
  const bpmAt = (timeMs: number) => changes.filter((c) => c.timeMs <= timeMs + 1e-6).at(-1)?.bpm ?? (changes[0] as Change).bpm;
  const barBeat = measures.map((b) => beatAt(changes, b.timeMs));

  const rows: ChartRow[] = [];
  // the measure a change falls in, and how far into it. on the bar line when it's within
  // SAME_POSITION_MS of one, a hair before the line included
  const place = (c: Change): { measure: number; beat: number } => {
    const tol = SAME_POSITION_MS / periodMs(c.bpm);
    let k = 0;
    for (let i = 0; i < barBeat.length; i += 1) if ((barBeat[i] as number) <= c.beat + tol) k = i;
    const into = Math.max(0, c.beat - (barBeat[k] as number));
    return { measure: k, beat: snapBeats(into, c.bpm) };
  };
  for (const c of changes) rows.push({ kind: "bpm", timeMs: c.timeMs, bpm: c.bpm, ...place(c) });

  let last: [number, number] | null = null;
  measures.forEach((bar, k) => {
    const region = grid.regions[bar.region];
    const m = region !== undefined && region.meter >= 0 ? meter[region.meter] : undefined;
    const nominal: [number, number] = m !== undefined ? [m.numerator, m.denominator] : [4, 4];
    let sig = nominal;
    const next = barBeat[k + 1];
    if (next !== undefined) {
      const length = snapBeats(next - (barBeat[k] as number), bpmAt(bar.timeMs));
      if (length !== barBeats(...nominal)) sig = signatureOf(length, nominal[1]);
    }
    if (last === null || last[0] !== sig[0] || last[1] !== sig[1]) {
      rows.push({ kind: "signature", timeMs: bar.timeMs, measure: k, beat: 0, numerator: sig[0], denominator: sig[1] });
      last = sig;
    }
  });

  // by position, a time signature before a bpm change at the same spot since it sets the measure
  rows.sort((a, b) => a.measure - b.measure || a.beat - b.beat || (a.kind === b.kind ? 0 : a.kind === "signature" ? -1 : 1));
  const paddingMs = decoderPaddingMs(source);
  return {
    measureZeroMs: zero.timeMs,
    firstMeasure: grid.firstMeasure,
    firstMeasureMs: (measures[grid.firstMeasure] ?? zero).timeMs,
    wavOffsetMs: -zero.timeMs,
    originalOffsetMs: -(zero.timeMs + paddingMs),
    paddingMs,
    kind: originalKind(source.filename),
    rows,
  };
}

function fraction(x: number): string | null {
  for (let d = 2; d <= MAX_FRACTION; d += 1) {
    const n = Math.round(x * d);
    if (n > 0 && n < d && Math.abs(x - n / d) < 1e-4) return `${n}/${d}`;
  }
  return null;
}

// beat 1 is the bar line. "beat 3" is two beats in, "beat 4 + 1/5" is 3.2 beats in
export function formatBeat(beatsIn: number): string {
  const whole = Math.floor(beatsIn + 1e-4);
  const rest = beatsIn - whole;
  if (Math.abs(rest) < 1e-4) return `beat ${whole + 1}`;
  const f = fraction(rest);
  return f !== null ? `beat ${whole + 1} + ${f}` : `beat ${(beatsIn + 1).toFixed(3)}`;
}

// ascii minus, it gets typed or pasted into a number field
export function formatOffset(ms: number): string {
  const v = Math.abs(ms) < 0.0005 ? 0 : ms;
  return `${v.toFixed(3)} ms`;
}

export function midMeasure(row: ChartRow): boolean {
  return row.beat !== 0;
}

// the pieces of a row as the panel shows them, the copied text joins the same pieces
export function rowParts(row: ChartRow, bpmDecimals: number): string[] {
  const parts = [`m.${row.measure}`];
  if (midMeasure(row)) parts.push(formatBeat(row.beat));
  parts.push(row.kind === "bpm" ? `${row.bpm.toFixed(bpmDecimals)} bpm` : `${row.numerator}/${row.denominator}`);
  if (midMeasure(row)) parts.push("mid-measure");
  return parts;
}

export function rowText(row: ChartRow, bpmDecimals: number): string {
  return rowParts(row, bpmDecimals).join(" · ");
}

// what the original file is called in the panel, its extension, the codec name for a wav is pcm_f32le
export function originalKind(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot + 1).toLowerCase() : "file";
}

export function setupText(setup: ChartSetup, bpmDecimals: number): string {
  const lines = [
    `offset with the wav from ffmpeg: ${formatOffset(setup.wavOffsetMs)}`,
    `offset with the original ${setup.kind}: ${formatOffset(setup.originalOffsetMs)}`,
    ...setup.rows.map((row) => rowText(row, bpmDecimals)),
  ];
  return `${lines.join("\n")}\n`;
}

// what goes on the timeline at a change: "m.21 · 130.00 bpm", "m.64 · 7/4", both when they share a line
export interface ChangeLabel {
  timeMs: number;
  text: string;
  // index of the first row it stands for, for picking it from the panel
  row: number;
}

export function changeLabels(setup: ChartSetup, bpmDecimals: number): ChangeLabel[] {
  const out: ChangeLabel[] = [];
  const firstOfKind = new Set<string>();
  setup.rows.forEach((row, i) => {
    // the first bpm and signature are where the chart starts, not changes, the band label shows them
    if (!firstOfKind.has(row.kind)) {
      firstOfKind.add(row.kind);
      return;
    }
    const value = row.kind === "bpm" ? `${row.bpm.toFixed(bpmDecimals)} bpm` : `${row.numerator}/${row.denominator}`;
    const prev = out[out.length - 1];
    const at = midMeasure(row) ? `m.${row.measure} ${formatBeat(row.beat)}` : `m.${row.measure}`;
    if (prev !== undefined && Math.abs(prev.timeMs - row.timeMs) < 0.5) prev.text += ` · ${value}`;
    else out.push({ timeMs: row.timeMs, text: `${at} · ${value}`, row: i });
  });
  return out;
}

// the music starts at the trim start, or at the first tracked beat when that's earlier. the
// timeline, the list and the plain answer all take it from here
export function chartStartFor(report: TimingReport, beats: BeatsFile | null, firstMeasure: number): ChartStart {
  return chartStartOf(report.trim.start_ms, beats?.beats[0]?.time_ms ?? null, firstMeasure);
}

export const FIRST_MEASURES = [0, 1] as const;
const FIRST_MEASURE_KEY = "starstep.firstMeasure";

// per browser, an editor's habit doesn't change between songs. storage can be off, then it's the default
export function storedFirstMeasure(): number {
  try {
    const raw = localStorage.getItem(FIRST_MEASURE_KEY);
    const value = Number(raw);
    return raw !== null && (FIRST_MEASURES as readonly number[]).includes(value) ? value : DEFAULT_FIRST_MEASURE;
  } catch {
    return DEFAULT_FIRST_MEASURE;
  }
}

export function storeFirstMeasure(value: number): void {
  try {
    localStorage.setItem(FIRST_MEASURE_KEY, String(value));
  } catch {
    // it just won't be remembered
  }
}
