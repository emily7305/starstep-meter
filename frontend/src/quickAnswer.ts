// the plain summary at the top of the page: bpm, offset, time signature, built from the chart
// setup list so the numbers can't differ from it. written for someone who doesn't read music,
// so no anchors, segments or grids in the words here

import { type ChartSetup, chartSetup, DEFAULT_OFFSET_SIGN, formatOffset, type OffsetSign } from "./chartSetup";
import { type ChartStart, chartStartOf, meterOrDefault, segmentAt, tempoGrid } from "./tempoMap";
import type { TimingReport } from "./types/timingReport";

export interface QuickAnswer {
  // the bpm the song starts at, the only one when it doesn't change
  bpm: number;
  // how many times the speed changes after the start
  bpmChanges: number;
  numerator: number;
  denominator: number;
  signatureChanges: number;
  wavOffsetMs: number;
  // null when the original file has no decoder padding, both offsets would be the same
  originalOffsetMs: number | null;
  // the original file's extension, mp3 or m4a
  kind: string;
  // a stretch under an auto segment came out low, see confidence_spans
  hardToRead: boolean;
}

export const HELP = {
  bpm: "how many beats there are in one minute. a chart editor asks for this to space the beats",
  offset: "where the first measure starts in the song. type it into the chart editor's music offset field",
  signature: "how many beats are in one measure, 4/4 is four",
} as const;

// the same grid and chart start the timeline numbers its bars with
export function setupFor(
  report: TimingReport,
  start: ChartStart = chartStartOf(report.trim.start_ms, null),
  offsetSign: OffsetSign = DEFAULT_OFFSET_SIGN,
): ChartSetup | null {
  const meter = meterOrDefault(report.meter_map, report.tempo_map);
  const grid = tempoGrid(report.tempo_map, meter, report.source.duration_ms, null, start);
  return chartSetup(grid, report.tempo_map, meter, report.source, offsetSign);
}

export function quickAnswer(report: TimingReport, setup: ChartSetup | null = setupFor(report)): QuickAnswer | null {
  if (setup === null) return null;
  const bpms = setup.rows.filter((r) => r.kind === "bpm");
  const signatures = setup.rows.filter((r) => r.kind === "signature");
  const firstBpm = bpms[0];
  const firstSig = signatures[0];
  if (firstBpm === undefined || firstBpm.kind !== "bpm" || firstSig === undefined || firstSig.kind !== "signature") return null;
  const map = report.tempo_map;
  const hardToRead = report.confidence_spans.some(
    (s) => s.low && map[segmentAt(map, (s.start_ms + s.end_ms) / 2)]?.source === "auto",
  );
  return {
    bpm: firstBpm.bpm,
    bpmChanges: bpms.length - 1,
    numerator: firstSig.numerator,
    denominator: firstSig.denominator,
    signatureChanges: signatures.length - 1,
    wavOffsetMs: setup.wavOffsetMs,
    originalOffsetMs: setup.paddingMs > 0 ? setup.originalOffsetMs : null,
    kind: setup.kind,
    hardToRead,
  };
}

function times(n: number): string {
  return n === 1 ? "once" : `${n} times`;
}

// "this song changes speed 3 times", null when nothing changes
export function changesLine(q: QuickAnswer): string | null {
  const parts: string[] = [];
  if (q.bpmChanges > 0) parts.push(`changes speed ${times(q.bpmChanges)}`);
  if (q.signatureChanges > 0) parts.push(`changes time signature ${times(q.signatureChanges)}`);
  return parts.length > 0 ? `this song ${parts.join(" and ")}` : null;
}

export function bpmLabel(q: QuickAnswer): string {
  return q.bpmChanges > 0 ? "bpm at the start" : "bpm";
}

export const WAV_LABEL = "if you load the wav made with ffmpeg";

export function originalLabel(q: QuickAnswer): string {
  return `if you load the original ${q.kind}`;
}

export const HARD_TO_READ = "parts of this song were hard to read, check the shaded areas";

// the card as plain text, the same lines it shows
export function quickText(q: QuickAnswer, bpmDecimals: number): string {
  const lines = [
    `${bpmLabel(q)}: ${q.bpm.toFixed(bpmDecimals)}`,
    `offset ${WAV_LABEL}: ${formatOffset(q.wavOffsetMs)}`,
  ];
  if (q.originalOffsetMs !== null) lines.push(`offset ${originalLabel(q)}: ${formatOffset(q.originalOffsetMs)}`);
  lines.push(`time signature: ${q.numerator}/${q.denominator}`);
  const changes = changesLine(q);
  if (changes !== null) lines.push(changes);
  if (q.hardToRead) lines.push(HARD_TO_READ);
  return `${lines.join("\n")}\n`;
}
