import { describe, expect, it } from "vitest";
import {
  beatSpacingPx,
  crispX,
  gridLines,
  nearestBeatMs,
  periodMs,
  timeToX,
  visibleLines,
  xToTime,
} from "./grid";
import type { GridLine, GridParams, View } from "./grid";

const DURATION_MS = 22000;
// 120 bpm is a 500 ms period. the half ms in the offset keeps view edges off the lines,
// so float noise in the scroll maths can't flip a count
const grid: GridParams = { offsetMs: 137.5, bpm: 120, beatsPerBar: 4 };

const zooms = [
  { name: "fit", totalWidthPx: 1000, pxPerMs: 1000 / 22000, spacingPx: (1000 / 22000) * 500 },
  { name: "200 px/s", totalWidthPx: 4400, pxPerMs: 0.2, spacingPx: 100 },
  { name: "2000 px/s", totalWidthPx: 44000, pxPerMs: 2, spacingPx: 1000 },
];

function view(totalWidthPx: number, scrollLeftPx: number, viewWidthPx: number): View {
  return { durationMs: DURATION_MS, totalWidthPx, scrollLeftPx, viewWidthPx };
}

const times = (lines: GridLine[]) => lines.map((line) => line.timeMs);
const indices = (lines: GridLine[]) => lines.map((line) => line.index);

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, i) => from + i);
}

describe("periodMs", () => {
  it("is the ms between beats", () => {
    expect(periodMs(120)).toBe(500);
    expect(periodMs(60)).toBe(1000);
  });
});

describe("timeToX and xToTime", () => {
  it.each(zooms)("round-trip at $name", ({ totalWidthPx }) => {
    for (const ms of [0, 137.5, 5000, 10137.5, 21999, DURATION_MS]) {
      const x = timeToX(ms, DURATION_MS, totalWidthPx);
      expect(xToTime(x, DURATION_MS, totalWidthPx)).toBeCloseTo(ms, 6);
    }
    for (const x of [0, 1, 275.5, totalWidthPx / 2, totalWidthPx]) {
      const ms = xToTime(x, DURATION_MS, totalWidthPx);
      expect(timeToX(ms, DURATION_MS, totalWidthPx)).toBeCloseTo(x, 6);
    }
  });

  it.each(zooms)("are linear at $name", ({ totalWidthPx, pxPerMs }) => {
    expect(timeToX(0, DURATION_MS, totalWidthPx)).toBe(0);
    expect(timeToX(DURATION_MS, DURATION_MS, totalWidthPx)).toBeCloseTo(totalWidthPx, 6);

    // a ms is the same width wherever it sits
    for (const ms of [0, 137.5, 8000, 21000]) {
      const step = timeToX(ms + 1, DURATION_MS, totalWidthPx) - timeToX(ms, DURATION_MS, totalWidthPx);
      expect(step).toBeCloseTo(pxPerMs, 9);
    }

    const a = timeToX(3000, DURATION_MS, totalWidthPx);
    const b = timeToX(4000, DURATION_MS, totalWidthPx);
    expect(timeToX(7000, DURATION_MS, totalWidthPx)).toBeCloseTo(a + b, 6);
  });

  it("puts 137.5 ms at x = 275 at 2000 px/s, and a 1 ms offset change is 2 px", () => {
    const total = 44000;
    expect(timeToX(137.5, DURATION_MS, total)).toBeCloseTo(275, 9);
    expect(xToTime(275, DURATION_MS, total)).toBeCloseTo(137.5, 9);

    const moved = timeToX(138.5, DURATION_MS, total) - timeToX(137.5, DURATION_MS, total);
    expect(moved).toBeCloseTo(2, 9);
  });

  it("return 0 instead of dividing by an empty song or width", () => {
    expect(timeToX(100, 0, 1000)).toBe(0);
    expect(xToTime(100, DURATION_MS, 0)).toBe(0);
  });
});

describe("gridLines", () => {
  it("puts index 0 at the offset and steps by the period", () => {
    const lines = gridLines(grid, 137.5, 2137.5);
    expect(indices(lines)).toEqual([0, 1, 2, 3, 4]);
    expect(times(lines)).toEqual([137.5, 637.5, 1137.5, 1637.5, 2137.5]);
  });

  it("gives lines before the offset negative indices", () => {
    const lines = gridLines(grid, -3862.5, 137.5);
    expect(indices(lines)).toEqual(range(-8, 0));
    expect(times(lines)).toEqual([
      -3862.5, -3362.5, -2862.5, -2362.5, -1862.5, -1362.5, -862.5, -362.5, 137.5,
    ]);
  });

  it("marks a bar every beatsPerBar indices, negative ones too", () => {
    const lines = gridLines(grid, -3862.5, 2137.5);
    expect(indices(lines)).toEqual(range(-8, 4));
    expect(lines.filter((line) => line.isBar).map((line) => line.index)).toEqual([-8, -4, 0, 4]);

    const byIndex = new Map(lines.map((line) => [line.index, line]));
    expect(byIndex.get(-1)?.isBar).toBe(false);
    expect(byIndex.get(-5)?.isBar).toBe(false);
    expect(byIndex.get(-4)?.isBar).toBe(true);
    expect(byIndex.get(-8)?.isBar).toBe(true);
  });

  it("follows a different beatsPerBar", () => {
    const lines = gridLines({ ...grid, beatsPerBar: 3 }, -3862.5, 2137.5);
    expect(lines.filter((line) => line.isBar).map((line) => line.index)).toEqual([-6, -3, 0, 3]);
    expect(lines.map((line) => line.bar)).toEqual([-3, -3, -2, -2, -2, -1, -1, -1, 0, 0, 0, 1, 1]);
  });

  it("numbers bars as floor(index / 4), so the bar before the first downbeat is -1", () => {
    const lines = gridLines(grid, -3862.5, 2137.5);
    expect(lines.map((line) => line.bar)).toEqual([-2, -2, -2, -2, -1, -1, -1, -1, 0, 0, 0, 0, 1]);
  });

  it("includes a line that sits exactly on either bound", () => {
    const lines = gridLines(grid, 637.5, 1637.5);
    expect(times(lines)).toEqual([637.5, 1137.5, 1637.5]);
  });

  it("leaves out a line just outside either bound", () => {
    const lines = gridLines(grid, 637.6, 1637.4);
    expect(times(lines)).toEqual([1137.5]);
  });

  it("returns the one line when both bounds are on it", () => {
    expect(times(gridLines(grid, 1137.5, 1137.5))).toEqual([1137.5]);
  });

  it("returns nothing for a range between two lines", () => {
    expect(gridLines(grid, 700, 800)).toEqual([]);
  });

  it("returns nothing for a bpm of 0 or less", () => {
    expect(gridLines({ ...grid, bpm: 0 }, 0, DURATION_MS)).toEqual([]);
    expect(gridLines({ ...grid, bpm: -120 }, 0, DURATION_MS)).toEqual([]);
  });

  it("returns nothing for fewer than one beat per bar", () => {
    expect(gridLines({ ...grid, beatsPerBar: 0 }, 0, DURATION_MS)).toEqual([]);
    expect(gridLines({ ...grid, beatsPerBar: -4 }, 0, DURATION_MS)).toEqual([]);
  });

  it("returns nothing when the end is before the start", () => {
    expect(gridLines(grid, 5000, 4999)).toEqual([]);
  });
});

describe("visibleLines", () => {
  it("returns every line of the song at fit zoom with no scroll", () => {
    const lines = visibleLines(grid, view(1000, 0, 1000));

    // 137.5 + 500 * n is still inside 22000 at n = 43, n = 44 would be 22137.5
    expect(lines).toHaveLength(44);
    expect(indices(lines.slice(1))).toEqual(range(1, 43));
    expect(lines[0]?.timeMs).toBe(137.5);
    expect(lines.at(-1)?.timeMs).toBe(21637.5);

    expect(lines[0]?.x).toBeCloseTo(6.25, 9);
    expect(lines.at(-1)?.x).toBeCloseTo(983.52, 2);
    for (const line of lines) {
      expect(line.x).toBeGreaterThanOrEqual(0);
      expect(line.x).toBeLessThanOrEqual(1000);
    }
  });

  it("numbers the first downbeat 0 when the view starts before it", () => {
    const [first] = visibleLines(grid, view(1000, 0, 1000));
    expect(first).toMatchObject({ timeMs: 137.5, index: 0, bar: 0, isBar: true });
  });

  it("keeps the lines before the first downbeat when they are inside the song", () => {
    const lines = visibleLines({ ...grid, offsetMs: 1200 }, view(1000, 0, 1000));
    expect(times(lines.slice(0, 4))).toEqual([200, 700, 1200, 1700]);
    expect(indices(lines.slice(0, 4))).toEqual([-2, -1, 0, 1]);
  });

  it("returns only the lines in a scrolled view at 200 px/s", () => {
    // 1000 px in is 5000 ms, 1200 px wide is 6000 ms, so 12 periods
    const lines = visibleLines(grid, view(4400, 1000, 1200));

    expect(lines).toHaveLength(12);
    expect(indices(lines)).toEqual(range(10, 21));
    expect(lines[0]?.timeMs).toBe(5137.5);
    expect(lines.at(-1)?.timeMs).toBe(10637.5);

    // 100 px between lines, first one 27.5 px into the view
    lines.forEach((line, i) => expect(line.x).toBeCloseTo(27.5 + i * 100, 6));
  });

  it("returns only the lines in a scrolled view at 2000 px/s", () => {
    // 20000 px in is 10000 ms and 1200 px is 600 ms, a bit more than one period
    const lines = visibleLines(grid, view(44000, 20000, 1200));

    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ timeMs: 10137.5, index: 20, bar: 5, isBar: true });
    expect(lines[0]?.x).toBeCloseTo(275, 6);
    expect(lines[0]?.x).toBe(timeToX(10137.5, DURATION_MS, 44000) - 20000);
  });

  it("can fit two lines in the same 600 ms when the view starts between them", () => {
    const lines = visibleLines(grid, view(44000, 20200, 1200));

    expect(times(lines)).toEqual([10137.5, 10637.5]);
    expect(indices(lines)).toEqual([20, 21]);
    expect(lines[0]?.x).toBeCloseTo(75, 6);
    expect(lines[1]?.x).toBeCloseTo(1075, 6);
  });

  it.each([
    { name: "200 px/s", total: 4400, scrollLeft: 1000, width: 1200 },
    { name: "2000 px/s", total: 44000, scrollLeft: 20000, width: 1200 },
    { name: "2000 px/s, other scroll", total: 44000, scrollLeft: 20200, width: 1200 },
    { name: "2000 px/s, near the end", total: 44000, scrollLeft: 43000, width: 1000 },
  ])("keeps every x inside the view at $name", ({ total, scrollLeft, width }) => {
    const lines = visibleLines(grid, view(total, scrollLeft, width));
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) {
      expect(line.x).toBeGreaterThanOrEqual(0);
      expect(line.x).toBeLessThanOrEqual(width);
      expect(line.x).toBe(timeToX(line.timeMs, DURATION_MS, total) - scrollLeft);
    }
  });

  it("stops at the end of the song when the view hangs past it", () => {
    // unclipped the view would reach 22500 ms and pick up the line at 22137.5
    const lines = visibleLines(grid, view(44000, 43000, 2000));
    expect(times(lines)).toEqual([21637.5]);
    expect(lines[0]?.x).toBeCloseTo(275, 6);
  });

  it("starts at 0 ms when the view is scrolled to a negative position", () => {
    // index -1 at -362.5 ms would land inside the view if it weren't clipped
    const lines = visibleLines(grid, view(44000, -1000, 2000));
    expect(times(lines)).toEqual([137.5]);
    expect(lines[0]?.x).toBeCloseTo(1275, 6);
  });
});

describe("beatSpacingPx", () => {
  it.each(zooms)("is the period in px at $name", ({ totalWidthPx, spacingPx }) => {
    expect(beatSpacingPx(grid, view(totalWidthPx, 0, 1000))).toBeCloseTo(spacingPx, 9);
  });

  it("is 22.7 px at fit zoom", () => {
    expect(beatSpacingPx(grid, view(1000, 0, 1000))).toBeCloseTo(22.7, 1);
  });

  it("doesn't depend on scroll, and follows the bpm", () => {
    expect(beatSpacingPx(grid, view(4400, 3000, 1200))).toBeCloseTo(100, 9);
    expect(beatSpacingPx({ ...grid, bpm: 60 }, view(4400, 0, 1200))).toBeCloseTo(200, 9);
  });
});

describe("crispX", () => {
  const xs = [0, 0.2, 10.3, 10.5, 99.99, 1234.567];

  // fractional part of the line centre in device px
  function deviceFraction(x: number, dpr: number, lineWidth: number): number {
    const device = crispX(x, dpr, lineWidth) * dpr;
    return device - Math.floor(device);
  }

  it.each([1, 2])("centres a 1 device px line on a half pixel at dpr %d", (dpr) => {
    for (const x of xs) expect(deviceFraction(x, dpr, 1)).toBe(0.5);
  });

  it.each([1, 2])("puts a 2 device px line on a whole device pixel at dpr %d", (dpr) => {
    for (const x of xs) expect(deviceFraction(x, dpr, 2)).toBe(0);
  });

  it("moves the line by at most a device pixel", () => {
    for (const dpr of [1, 2]) {
      for (const x of xs) expect(Math.abs(crispX(x, dpr, 1) - x)).toBeLessThanOrEqual(1 / dpr);
    }
  });

  it("snaps to known positions", () => {
    expect(crispX(10.3, 1, 1)).toBe(10.5);
    expect(crispX(10.3, 2, 1)).toBe(10.75);
    expect(crispX(10.3, 1, 2)).toBe(10);
    expect(crispX(10.3, 2, 2)).toBe(10.5);
  });
});

describe("nearestBeatMs", () => {
  it("rounds to the closest line on either side", () => {
    expect(nearestBeatMs(grid, 137.5 + 240)).toBe(137.5);
    expect(nearestBeatMs(grid, 137.5 + 260)).toBe(637.5);
    expect(nearestBeatMs(grid, 137.5 - 240)).toBe(137.5);
    expect(nearestBeatMs(grid, 137.5 - 260)).toBe(-362.5);
  });

  it("returns a time that is already on a line unchanged", () => {
    expect(nearestBeatMs(grid, 10137.5)).toBe(10137.5);
    expect(nearestBeatMs(grid, 21800)).toBe(21637.5);
  });
});
