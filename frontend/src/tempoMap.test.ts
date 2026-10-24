import { describe, expect, it } from "vitest";
import { periodMs } from "./grid";
import { bands, EDGE_FRACTION, mapLines, nearestLineMs, segmentAt, tempoGrid, visibleMapLines } from "./tempoMap";
import type { TempoSegment } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number, source: "auto" | "manual" = "auto"): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: source === "auto" ? 1 : null, source, ratio_merged: [] };
}

const DURATION_MS = 40000;
// 120 bpm from the first downbeat at 1000, then 150 bpm from the beat at 17000 on, continuous phase
const one = [seg(1000, 38000, 120, 1000)];
const two = [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 17000)];
const three = [seg(1000, 9000, 120, 1000), seg(9000, 17000, 240, 9000), seg(17000, 38000, 120, 17000, "manual")];

const times = (lines: { timeMs: number }[]) => lines.map((l) => l.timeMs);

describe("tempoGrid and mapLines", () => {
  it("is the single grid for a one segment map, from 0 to the end of the audio", () => {
    const grid = tempoGrid(one, DURATION_MS, 4);
    const lines = mapLines(grid, 0, DURATION_MS);

    expect(lines[0]?.timeMs).toBe(0);
    expect(lines[0]?.index).toBe(-2);
    expect(lines.at(-1)?.timeMs).toBe(39500);
    expect(lines.find((l) => l.timeMs === 1000)).toMatchObject({ index: 0, bar: 0, isBar: true, segment: 0 });
  });

  it("switches period at the boundary and draws one line on it", () => {
    const lines = mapLines(tempoGrid(two, DURATION_MS, 4), 15000, 18500);

    expect(times(lines)).toEqual([15000, 15500, 16000, 16500, 17000, 17400, 17800, 18200]);
    expect(lines.map((l) => l.segment)).toEqual([0, 0, 0, 0, 1, 1, 1, 1]);
  });

  it("gives a line just before a boundary to the next segment", () => {
    // the second anchor a little early, its first line sits 3 ms before the boundary
    const map = [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 16997)];
    const lines = mapLines(tempoGrid(map, DURATION_MS, 4), 16000, 17500);

    expect(times(lines)).toEqual([16000, 16500, 16997, 17397]);
    expect(EDGE_FRACTION * periodMs(150)).toBeGreaterThan(3);
  });

  it("keeps bar numbers counting across segments", () => {
    const lines = mapLines(tempoGrid(two, DURATION_MS, 4), 0, DURATION_MS).filter((l) => l.isBar);
    const bars = lines.map((l) => l.bar);

    // 120 bpm bars every 2000 ms up to 15000 is bars 0-7, 150 bpm bars every 1600 ms carry on from 8
    expect(lines.find((l) => l.timeMs === 15000)?.bar).toBe(7);
    expect(lines.find((l) => l.timeMs === 17000)?.bar).toBe(8);
    expect(lines.find((l) => l.timeMs === 18600)?.bar).toBe(9);
    expect(new Set(bars).size).toBe(bars.length);
    expect(bars).toEqual([...bars].sort((a, b) => a - b));
  });

  it("starts each later segment's bars at its anchor", () => {
    // anchor two beats into the segment, the two beats before it belong to the previous bar
    const map = [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 17800)];
    const lines = mapLines(tempoGrid(map, DURATION_MS, 4), 16900, 19500);

    expect(lines.map((l) => [l.timeMs, l.isBar, l.bar])).toEqual([
      [17000, false, 7],
      [17400, false, 7],
      [17800, true, 8],
      [18200, false, 8],
      [18600, false, 8],
      [19000, false, 8],
      [19400, true, 9],
    ]);
  });

  it("draws a nudged anchor that the server doesn't have yet", () => {
    const grid = tempoGrid(two, DURATION_MS, 4, { segment: 1, anchorMs: 17003 });

    expect(times(mapLines(grid, 16900, 17900))).toEqual([17003, 17403, 17803]);
  });

  it("returns nothing for an empty or backwards range", () => {
    const grid = tempoGrid(two, DURATION_MS, 4);
    expect(mapLines(grid, 5000, 4000)).toEqual([]);
    expect(mapLines(tempoGrid(two, DURATION_MS, 0), 0, DURATION_MS)).toEqual([]);
  });
});

describe("visibleMapLines", () => {
  it("places lines from both segments in a view across the boundary", () => {
    // 2000 px/s, view of 2 s from 16 s
    const view = { durationMs: DURATION_MS, totalWidthPx: 80000, scrollLeftPx: 32000, viewWidthPx: 4000 };
    const lines = visibleMapLines(tempoGrid(two, DURATION_MS, 4), view);

    expect(times(lines)).toEqual([16000, 16500, 17000, 17400, 17800]);
    expect(lines.map((l) => l.x)).toEqual([0, 1000, 2000, 2800, 3600]);
  });
});

describe("segmentAt", () => {
  it("finds the segment by its start", () => {
    expect(segmentAt(three, 1000)).toBe(0);
    expect(segmentAt(three, 8999.9)).toBe(0);
    expect(segmentAt(three, 9000)).toBe(1);
    expect(segmentAt(three, 30000)).toBe(2);
  });

  it("clamps to the first and last segment", () => {
    expect(segmentAt(three, 0)).toBe(0);
    expect(segmentAt(three, 39999)).toBe(2);
    expect(segmentAt([], 100)).toBe(-1);
  });
});

describe("nearestLineMs", () => {
  it("rounds to the closest line on either side of a boundary", () => {
    const grid = tempoGrid(three, DURATION_MS, 4);
    expect(nearestLineMs(grid, 8800)).toBe(9000);
    expect(nearestLineMs(grid, 9130)).toBe(9250);
    expect(nearestLineMs(grid, 16990)).toBe(17000);
  });
});

describe("bands", () => {
  it("has one band per segment with its bpm and source", () => {
    expect(bands(three)).toEqual([
      { index: 0, startMs: 1000, endMs: 9000, bpm: 120, manual: false },
      { index: 1, startMs: 9000, endMs: 17000, bpm: 240, manual: false },
      { index: 2, startMs: 17000, endMs: 38000, bpm: 120, manual: true },
    ]);
  });
});
