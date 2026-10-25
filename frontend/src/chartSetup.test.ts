import { describe, expect, it } from "vitest";
import { changeLabels, chartSetup, formatBeat, formatOffset, rowText, setupText, type ChartRow } from "./chartSetup";
import { wavName } from "./components/ChartSetup";
import { mapLines, tempoGrid } from "./tempoMap";
import type { AudioSource, MeterSegment, TempoSegment } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: 1, source: "auto", ratio_merged: [] };
}

function meter(start: number, end: number, numerator: number, denominator = 4): MeterSegment {
  return { start_ms: start, end_ms: end, numerator, denominator, confidence: null, source: "auto" };
}

const MP3: AudioSource = {
  filename: "song.mp3",
  sha256: "0".repeat(64),
  duration_ms: 60000,
  sample_rate: 48000,
  codec: "mp3",
  decoder_padding_samples: 1105,
};

function setupOf(map: TempoSegment[], meters: MeterSegment[], source = MP3) {
  const grid = tempoGrid(map, meters, source.duration_ms);
  const setup = chartSetup(grid, map, meters, source);
  if (setup === null) throw new Error("no setup");
  return { grid, setup };
}

const brief = (rows: ChartRow[]) =>
  rows.map((r) => [r.measure, r.beat, r.kind === "bpm" ? r.bpm : `${r.numerator}/${r.denominator}`]);

// 120 bpm from the first downbeat at 500, 150 bpm from bar 8 (16500) on, 7/4 from 4 bars later
const MAP = [seg(400, 16500, 120, 500), seg(16500, 59000, 150, 16500)];
const METER = [meter(400, 22900, 4), meter(22900, 59000, 7)];

describe("chartSetup", () => {
  it("lists the tempo change and the meter change at the right measures", () => {
    const { setup } = setupOf(MAP, METER);

    expect(brief(setup.rows)).toEqual([
      [0, 0, "4/4"],
      [0, 0, 120],
      [8, 0, 150],
      [12, 0, "7/4"],
    ]);
    expect(setup.measureZeroMs).toBe(500);
  });

  it("gives the offset as minus where measure 0 starts, and the mp3 one minus its padding too", () => {
    const { setup } = setupOf(MAP, METER);

    expect(formatOffset(setup.wavOffsetMs)).toBe("-500.000 ms");
    // 1105 samples at 48 khz, mikumikuworld plays the mp3's padding
    expect(setup.paddingMs).toBeCloseTo(23.021, 3);
    expect(formatOffset(setup.originalOffsetMs)).toBe("-523.021 ms");
  });

  it("matches the by-ear check on MisoilePunch, measure 0 at 62.362 ms", () => {
    // its report: 270.0038 bpm, first downbeat at 951.238, mp3 at 48 khz
    const map = [seg(119.521, 134213.979, 270.0038, 951.238)];
    const { setup } = setupOf(map, [meter(119.521, 134213.979, 4)], { ...MP3, duration_ms: 137024 });

    expect(formatOffset(setup.wavOffsetMs)).toBe("-62.362 ms");
    // -62.3615 - 23.0208, adding the two rounded values gives -85.383
    expect(formatOffset(setup.originalOffsetMs)).toBe("-85.382 ms");
  });

  it("rounds the mp3 offset only for display, the two differ by exactly the padding", () => {
    // MisoilePunch: bar 0 at 62.3615 ms and 1105 samples of padding at 48 khz (23.0208 ms)
    const map = [seg(119.521, 134213.979, 270.0038, 951.238)];
    const { setup } = setupOf(map, [meter(119.521, 134213.979, 4)], { ...MP3, duration_ms: 137024 });

    expect(setup.wavOffsetMs - setup.originalOffsetMs).toBeCloseTo(1105 / 48, 9);
    expect(formatOffset(setup.wavOffsetMs)).toBe("-62.362 ms");
    expect(formatOffset(-setup.paddingMs)).toBe("-23.021 ms");
    // adding the two rounded values would give -85.383
    expect(formatOffset(setup.originalOffsetMs)).toBe("-85.382 ms");
  });

  it("starts measure 0 at the first bar line in the audio, before the first downbeat if there's room", () => {
    // first downbeat at 2300 with 2000 ms bars, so there's a bar line at 300 too
    const map = [seg(200, 59000, 120, 2300)];
    const { grid, setup } = setupOf(map, []);

    expect(setup.measureZeroMs).toBe(300);
    expect(grid.bars[0]).toMatchObject({ timeMs: 300, bar: 0 });
    expect(grid.bars[1]).toMatchObject({ timeMs: 2300, bar: 1 });
  });

  it("shows a change that isn't on beat 1 with its beat, as mid-measure", () => {
    // 150 bpm from 15000, two beats into the bar at 14000, its own bars from 15800
    const map = [seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15800)];
    const { setup } = setupOf(map, []);
    const change = setup.rows.find((r) => r.kind === "bpm" && r.bpm === 150);

    expect(change).toMatchObject({ measure: 7, beat: 2 });
    expect(rowText(change as ChartRow, 2)).toBe("m.7 · beat 3 · 150.00 bpm · mid-measure");
    // the bar it sits in is still a full 4/4, two beats at each tempo
    expect(setup.rows.filter((r) => r.kind === "signature")).toHaveLength(1);
  });

  it("shows a change on a fractional beat as a fraction", () => {
    // the second grid doesn't carry on from the first, its first line is 2.2 beats into the bar
    // at 14000 and its own bars start two beats later
    const map = [seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15900)];
    const { setup } = setupOf(map, []);
    const change = setup.rows.find((r) => r.kind === "bpm" && r.bpm === 150) as ChartRow;

    expect(change.measure).toBe(7);
    expect(change.beat).toBeCloseTo(2.2, 9);
    expect(rowText(change, 2)).toBe("m.7 · beat 3 + 1/5 · 150.00 bpm · mid-measure");
  });

  it("doesn't make a cut bar of a handover a fraction of a ms off a whole beat", () => {
    // what the 120 -> 150 click track gives, two fits that meet 0.77 ms off the first one's beat
    const map = [seg(709.546, 48709.274, 120.0011, 708.946), seg(48709.274, 59000, 150, 48709.274)];
    const { setup } = setupOf(map, []);
    expect(brief(setup.rows)).toEqual([
      [0, 0, "4/4"],
      [0, 0, 120.0011],
      [24, 0, 150],
    ]);
  });

  it("uses the same measure numbers as the timeline's bar labels", () => {
    const cases: [TempoSegment[], MeterSegment[]][] = [
      [MAP, METER],
      [[seg(200, 59000, 120, 2300)], []],
      [[seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15800)], []],
    ];
    for (const [map, meters] of cases) {
      const { grid, setup } = setupOf(map, meters);
      for (const row of setup.rows) {
        // the bar line the timeline draws where the measure starts carries that number
        const start = row.kind === "signature" ? row.timeMs : (grid.bars[row.measure]?.timeMs as number);
        const label = mapLines(grid, start - 1, start + 1).find((l) => l.isBar && Math.abs(l.timeMs - start) < 0.5);
        expect(label?.bar).toBe(row.measure);
        // and a bpm change sits inside that measure
        const next = grid.bars[row.measure + 1]?.timeMs ?? Infinity;
        expect(row.timeMs).toBeGreaterThanOrEqual(start - 1e-6);
        expect(row.timeMs).toBeLessThan(next);
      }
    }
  });

  it("copies the same lines the panel shows, one change per line", () => {
    const { setup } = setupOf(MAP, METER);
    const lines = setupText(setup, 2).trimEnd().split("\n");

    expect(lines.slice(0, 2)).toEqual([
      "offset with the wav from ffmpeg: -500.000 ms",
      "offset with the original mp3: -523.021 ms",
    ]);
    expect(lines.slice(2)).toEqual(setup.rows.map((r) => rowText(r, 2)));
    expect(lines.slice(2)).toEqual(["m.0 · 4/4", "m.0 · 120.00 bpm", "m.8 · 150.00 bpm", "m.12 · 7/4"]);
  });

  it("shows more decimals when asked", () => {
    const { setup } = setupOf([seg(0, 59000, 270.0038, 951.238)], []);
    const bpm = setup.rows.find((r) => r.kind === "bpm") as ChartRow;
    expect(rowText(bpm, 2)).toBe("m.0 · 270.00 bpm");
    expect(rowText(bpm, 4)).toBe("m.0 · 270.0038 bpm");
  });

  it("labels each change on the timeline, not the starting values", () => {
    const { setup } = setupOf(MAP, METER);
    expect(changeLabels(setup, 2).map((l) => [l.timeMs, l.text])).toEqual([
      [16500, "m.8 · 150.00 bpm"],
      [22900, "m.12 · 7/4"],
    ]);
  });

  it("puts a tempo and a meter change on the same line into one label", () => {
    const map = [seg(400, 16500, 120, 500), seg(16500, 59000, 150, 16500)];
    const { setup } = setupOf(map, [meter(400, 16500, 4), meter(16500, 59000, 3)]);
    expect(changeLabels(setup, 2).map((l) => l.text)).toEqual(["m.8 · 3/4 · 150.00 bpm"]);
  });
});

describe("wavName", () => {
  it("names the converted wav after the song without writing over a wav", () => {
    expect(wavName("song.mp3")).toBe("song.wav");
    expect(wavName("【音源】YOUNITHM.mp3")).toBe("【音源】YOUNITHM.wav");
    expect(wavName("click.WAV")).toBe("click-ffmpeg.wav");
  });
});

describe("formatBeat", () => {
  it("counts from beat 1 on the bar line", () => {
    expect(formatBeat(0)).toBe("beat 1");
    expect(formatBeat(2)).toBe("beat 3");
    expect(formatBeat(1.5)).toBe("beat 2 + 1/2");
    expect(formatBeat(2 + 1 / 3)).toBe("beat 3 + 1/3");
    expect(formatBeat(0.123)).toBe("beat 1.123");
  });
});
