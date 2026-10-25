import { describe, expect, it } from "vitest";
import { periodMs } from "./grid";
import {
  appliedSegment,
  bands,
  EDGE_FRACTION,
  mapLines,
  meterOrDefault,
  nearestLineMs,
  segmentAt,
  splitOutSegment,
  tempoGrid,
  visibleMapLines,
} from "./tempoMap";
import type { MeterSegment, TempoSegment } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number, source: "auto" | "manual" = "auto"): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: source === "auto" ? 1 : null, source, notation_scale: 1, ratio_merged: [] };
}

const DURATION_MS = 40000;
// 120 bpm from the first downbeat at 1000, then 150 bpm from the beat at 17000 on, continuous phase
const one = [seg(1000, 38000, 120, 1000)];
const two = [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 17000)];
const three = [seg(1000, 9000, 120, 1000), seg(9000, 17000, 240, 9000), seg(17000, 38000, 120, 17000, "manual")];

const times = (lines: { timeMs: number }[]) => lines.map((l) => l.timeMs);
const barTimes = (lines: { timeMs: number; isBar: boolean }[]) => times(lines.filter((l) => l.isBar));

function meter(start: number, end: number, numerator: number, denominator = 4, source: "auto" | "manual" = "auto"): MeterSegment {
  return { start_ms: start, end_ms: end, numerator, denominator, confidence: null, source };
}

describe("tempoGrid and mapLines", () => {
  it("is the single grid for a one segment map, from 0 to the end of the audio", () => {
    const grid = tempoGrid(one, [], DURATION_MS);
    const lines = mapLines(grid, 0, DURATION_MS);

    expect(lines[0]?.timeMs).toBe(0);
    expect(lines[0]?.index).toBe(-2);
    expect(lines.at(-1)?.timeMs).toBe(39500);
    expect(lines.find((l) => l.timeMs === 1000)).toMatchObject({ index: 0, bar: 0, isBar: true, segment: 0 });
  });

  it("switches period at the boundary and draws one line on it", () => {
    const lines = mapLines(tempoGrid(two, [], DURATION_MS), 15000, 18500);

    expect(times(lines)).toEqual([15000, 15500, 16000, 16500, 17000, 17400, 17800, 18200]);
    expect(lines.map((l) => l.segment)).toEqual([0, 0, 0, 0, 1, 1, 1, 1]);
  });

  it("gives a line just before a boundary to the next segment", () => {
    // the second anchor a little early, its first line sits 3 ms before the boundary
    const map = [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 16997)];
    const lines = mapLines(tempoGrid(map, [], DURATION_MS), 16000, 17500);

    expect(times(lines)).toEqual([16000, 16500, 16997, 17397]);
    expect(EDGE_FRACTION * periodMs(150)).toBeGreaterThan(3);
  });

  it("keeps bar numbers counting across segments", () => {
    const lines = mapLines(tempoGrid(two, [], DURATION_MS), 0, DURATION_MS).filter((l) => l.isBar);
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
    const lines = mapLines(tempoGrid(map, [], DURATION_MS), 16900, 19500);

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
    const grid = tempoGrid(two, [], DURATION_MS, { segment: 1, anchorMs: 17003 });

    expect(times(mapLines(grid, 16900, 17900))).toEqual([17003, 17403, 17803]);
  });

  it("returns nothing for an empty or backwards range", () => {
    const grid = tempoGrid(two, [], DURATION_MS);
    expect(mapLines(grid, 5000, 4000)).toEqual([]);
  });
});

describe("visibleMapLines", () => {
  it("places lines from both segments in a view across the boundary", () => {
    // 2000 px/s, view of 2 s from 16 s
    const view = { durationMs: DURATION_MS, totalWidthPx: 80000, scrollLeftPx: 32000, viewWidthPx: 4000 };
    const lines = visibleMapLines(tempoGrid(two, [], DURATION_MS), view);

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
    const grid = tempoGrid(three, [], DURATION_MS);
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

// the same cases as tests/test_bars.py, the backend snaps suggestions and applies them with this rule
describe("bar lines from the meter map", () => {
  it("is 4/4 from the anchor with no meter map", () => {
    const lines = mapLines(tempoGrid([seg(100, 10100, 120, 600)], [], 10100), 0, 10100);
    expect(barTimes(lines)).toEqual([600, 2600, 4600, 6600, 8600]);
  });

  it("counts a meter that starts with the segment from the anchor", () => {
    const lines = mapLines(tempoGrid([seg(100, 10100, 120, 600)], [meter(100, 10100, 3)], 10100), 0, 10100);
    expect(barTimes(lines)).toEqual([600, 2100, 3600, 5100, 6600, 8100, 9600]);
  });

  it("restarts the bars where a meter changes inside a segment", () => {
    const grid = tempoGrid([seg(0, 20000, 120, 0)], [meter(0, 4000, 4), meter(4000, 20000, 7)], 20000);
    expect(barTimes(mapLines(grid, 0, 19999))).toEqual([0, 2000, 4000, 7500, 11000, 14500, 18000]);
    expect(grid.bars.map((b) => b.bar)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  });

  it("snaps a meter change off the grid onto the nearest beat", () => {
    const grid = tempoGrid([seg(0, 10000, 120, 0)], [meter(0, 3010, 4), meter(3010, 10000, 4)], 10000);
    expect(barTimes(mapLines(grid, 0, 9999))).toEqual([0, 2000, 3000, 5000, 7000, 9000]);
  });

  it("draws a 7/8 bar line between two beats", () => {
    const lines = mapLines(tempoGrid([seg(0, 7100, 120, 0)], [meter(0, 7100, 7, 8)], 7100), 0, 7099);
    expect(barTimes(lines)).toEqual([0, 1750, 3500, 5250, 7000]);
    // the beats are still every 500 ms, 15 of them and 3 are bar lines, 1750 is none of them
    expect(lines.filter((l) => !l.isBar).length).toBe(12);
  });

  it("makes bars twice as long where a span is set to half the bpm", () => {
    const full = tempoGrid([seg(0, 16000, 240, 0)], [meter(0, 16000, 4)], 16000);
    const halved = tempoGrid(
      [seg(0, 4000, 240, 0), seg(4000, 12000, 120, 4000), seg(12000, 16000, 240, 12000)],
      [meter(0, 16000, 4)],
      16000,
    );
    const inSpan = (grid: ReturnType<typeof tempoGrid>) => grid.bars.filter((b) => b.timeMs >= 4000 && b.timeMs < 12000);
    expect(inSpan(full).length).toBe(8);
    expect(inSpan(halved).length).toBe(4);
    // and the lines outside it don't move
    expect(times(mapLines(halved, 0, 3999))).toEqual(times(mapLines(full, 0, 3999)));
    expect(times(mapLines(halved, 12000, 16000))).toEqual(times(mapLines(full, 12000, 16000)));
  });

  it("numbers the first downbeat bar 0", () => {
    const grid = tempoGrid([seg(0, 10000, 120, 1000)], [meter(0, 10000, 4)], 10000);
    expect(grid.bars.map((b) => [b.timeMs, b.bar])).toEqual([
      [1000, 0],
      [3000, 1],
      [5000, 2],
      [7000, 3],
      [9000, 4],
    ]);
  });

  it("thins bars by the shortest bar in a segment", () => {
    const grid = tempoGrid([seg(0, 20000, 120, 0)], [meter(0, 4000, 4), meter(4000, 20000, 3)], 20000);
    expect(grid.segments[0]?.barBeats).toBe(3);
  });
});

describe("meterOrDefault and appliedSegment", () => {
  it("stands in a 4/4 for a report with no meter map", () => {
    expect(meterOrDefault([], three)).toEqual([meter(1000, 38000, 4)]);
    expect(meterOrDefault([meter(1000, 38000, 3)], three)).toEqual([meter(1000, 38000, 3)]);
  });

  it("follows the span of an applied suggestion to its new segment", () => {
    const half = { start_ms: 21000, end_ms: 29000, kind: "half", suggested_bpm: 60, grid_bpm: 120, score: 0.6, status: "open" } as const;
    expect(appliedSegment(three, half)).toBe(3);
    expect(appliedSegment(three, { ...half, start_ms: 17000 })).toBe(2);
    expect(appliedSegment(three, { ...half, kind: "fold", start_ms: 17000, end_ms: 38000 })).toBe(1);
  });
});

describe("splitOutSegment", () => {
  const felt = (start: number, end: number) => ({ start_ms: start, end_ms: end, bpm: 90, ratio: "3/4", fit: 1 });

  it("lands on the kept section once it's split out", () => {
    const map = [seg(1000, 38000, 120, 1000)];
    map[0] = { ...map[0], ratio_merged: [felt(9000, 17000)] } as TempoSegment;

    expect(splitOutSegment(map, 0, 0)).toBe(1);
  });

  it("stays put when the section starts with the segment, only its end gets cut", () => {
    // 200 ms in is under half a 500 ms beat, the server doesn't cut there
    const map = [seg(1000, 38000, 120, 1000)];
    map[0] = { ...map[0], ratio_merged: [felt(1200, 17000)] } as TempoSegment;

    expect(splitOutSegment(map, 0, 0)).toBe(0);
    expect(splitOutSegment(map, 0, 3)).toBe(0);
  });
});
