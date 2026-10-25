import { describe, expect, it } from "vitest";
import { changeLabels, chartSetup, formatBeat, formatOffset, type OffsetSign, rowText, setupText, type ChartRow } from "./chartSetup";
import { wavName } from "./components/ChartSetup";
import { type ChartStart, chartStartOf, mapLines, tempoGrid } from "./tempoMap";
import type { AudioSource, MeterSegment, TempoSegment } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: 1, source: "auto", notation_scale: 1, ratio_merged: [] };
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

// the app's rule: the music starts at the trim start, which is the first segment's start
function setupOf(map: TempoSegment[], meters: MeterSegment[], source = MP3, start?: ChartStart, sign: OffsetSign = "later") {
  const grid = tempoGrid(map, meters, source.duration_ms, null, start ?? chartStartOf(map[0]?.start_ms ?? 0, null));
  const setup = chartSetup(grid, map, meters, source, sign);
  if (setup === null) throw new Error("no setup");
  return { grid, setup };
}

const brief = (rows: ChartRow[]) =>
  rows.map((r) => [r.measure, r.beat, r.kind === "bpm" ? r.bpm : `${r.numerator}/${r.denominator}`]);

// 120 bpm from the first downbeat at 500, 150 bpm 8 bars later (16500), 7/4 four bars after that.
// the music starts on the first downbeat, so that's measure 1 and measure 0 is the bar before it
const MAP = [seg(400, 16500, 120, 500), seg(16500, 59000, 150, 16500)];
const METER = [meter(400, 22900, 4), meter(22900, 59000, 7)];

// the bar line a measure starts on, drawn or worked out back past 0 ms
function measureStart(grid: ReturnType<typeof tempoGrid>, measure: number): number {
  const bar = grid.bars.find((b) => b.bar === measure);
  if (bar !== undefined) return bar.timeMs;
  const first = grid.bars.find((b) => b.bar >= 0) as { timeMs: number; bar: number };
  return first.timeMs - (first.bar - measure) * (grid.regions[0]?.barMs ?? 0);
}

describe("chartSetup", () => {
  it("lists the tempo change and the meter change at the right measures", () => {
    const { setup } = setupOf(MAP, METER);

    expect(brief(setup.rows)).toEqual([
      [0, 0, "4/4"],
      [0, 0, 120],
      [9, 0, 150],
      [13, 0, "7/4"],
    ]);
    expect(setup.firstMeasure).toBe(1);
    expect(setup.firstMeasureMs).toBe(500);
    expect(setup.measureZeroMs).toBe(-1500);
  });

  it("gives the offset as minus where measure 0 starts, positive when that's before the audio", () => {
    const { setup } = setupOf(MAP, METER);

    // less than a bar of silence, so measure 0 starts 1500 ms before the file and the song starts later
    expect(formatOffset(setup.wavOffsetMs)).toBe("1500.000 ms");
    // 1105 samples at 48 khz, an editor that plays the mp3's padding needs that much more
    expect(setup.paddingMs).toBeCloseTo(23.021, 3);
    expect(formatOffset(setup.originalOffsetMs)).toBe("1476.979 ms");
  });

  it("skips a long silent start, the music's first downbeat is measure 1", () => {
    // 8 s of silence before the first downbeat at 120 bpm, bar lines every 2000 ms from 0
    const map = [seg(8000, 59000, 120, 8000)];
    const { grid, setup } = setupOf(map, [], MP3, chartStartOf(8000, 7999.3));

    expect(setup.firstMeasureMs).toBe(8000);
    expect(setup.measureZeroMs).toBe(6000);
    expect(formatOffset(setup.wavOffsetMs)).toBe("-6000.000 ms");
    expect(formatOffset(setup.originalOffsetMs)).toBe("-6023.021 ms");
    expect(grid.bars.map((b) => [b.timeMs, b.bar]).slice(0, 6)).toEqual([
      [0, -3],
      [2000, -2],
      [4000, -1],
      [6000, 0],
      [8000, 1],
      [10000, 2],
    ]);
  });

  it("skips a long silent start at a tempo that isn't round", () => {
    // like real_d, about 8 s of silence at 145.99 bpm
    const bar = (4 * 60000) / 145.99;
    const map = [seg(8123.4, 59000, 145.99, 8123.4)];
    const { setup } = setupOf(map, [], MP3, chartStartOf(8123.4, 8122.7));

    expect(setup.firstMeasureMs).toBeCloseTo(8123.4, 9);
    expect(setup.wavOffsetMs).toBeCloseTo(-(8123.4 - bar), 9);
    expect(formatOffset(setup.wavOffsetMs)).toBe("-6479.452 ms");
  });

  it("puts measure 1 on the first downbeat with less than a bar of silence, and the offset is positive", () => {
    const map = [seg(500, 59000, 120, 500)];
    const { grid, setup } = setupOf(map, [], MP3, chartStartOf(500, 499.3));

    expect(grid.bars[0]).toMatchObject({ timeMs: 500, bar: 1 });
    expect(setup.measureZeroMs).toBe(-1500);
    expect(setup.wavOffsetMs).toBeGreaterThan(0);
    expect(formatOffset(setup.wavOffsetMs)).toBe("1500.000 ms");
    // the beats before the first drawn bar line are in measure 0, not before the chart
    expect(mapLines(grid, 0, 400).map((l) => l.bar)).toEqual([0]);
  });

  it("puts measure 1 on the bar that holds a pickup", () => {
    // first downbeat at 2300 with 2000 ms bars, a pickup beat at 1800 where the music starts
    const map = [seg(1800, 59000, 120, 2300)];
    const { grid, setup } = setupOf(map, [], MP3, chartStartOf(1800, 1799.3));

    expect(setup.firstMeasureMs).toBe(300);
    expect(grid.bars[0]).toMatchObject({ timeMs: 300, bar: 1 });
    expect(grid.bars[1]).toMatchObject({ timeMs: 2300, bar: 2 });
    expect(formatOffset(setup.wavOffsetMs)).toBe("1700.000 ms");
  });

  it("takes the first tracked beat when it comes before the trim start", () => {
    // trim a little late on a soft attack, the first beat on the bar line at 8000
    const map = [seg(8030, 59000, 120, 8000)];
    const late = setupOf(map, [], MP3, chartStartOf(8300, null));
    const beat = setupOf(map, [], MP3, chartStartOf(8300, 7999.3));
    expect(late.setup.firstMeasureMs).toBe(8000);
    expect(beat.setup.firstMeasureMs).toBe(8000);
  });

  it("starts the music at measure 0 when that's the setting", () => {
    const map = [seg(8000, 59000, 120, 8000)];
    const { grid, setup } = setupOf(map, [], MP3, chartStartOf(8000, 7999.3, 0));

    expect(setup.firstMeasure).toBe(0);
    expect(setup.measureZeroMs).toBe(8000);
    expect(formatOffset(setup.wavOffsetMs)).toBe("-8000.000 ms");
    expect(grid.bars.find((b) => b.timeMs === 8000)?.bar).toBe(0);
    expect(grid.bars.find((b) => b.timeMs === 6000)?.bar).toBe(-1);
  });

  it("rounds the mp3 offset only for display, the two differ by exactly the padding", () => {
    // real_a: 270.0038 bpm, first downbeat at 951.238, the music from 119.521. measure 1 is
    // the bar line at 62.3615, measure 0 a bar before that, and 1105 samples of padding at 48 khz
    const map = [seg(119.521, 134213.979, 270.0038, 951.238)];
    const { setup } = setupOf(map, [meter(119.521, 134213.979, 4)], { ...MP3, duration_ms: 137024 });

    expect(formatOffset(setup.firstMeasureMs)).toBe("62.362 ms");
    expect(setup.wavOffsetMs - setup.originalOffsetMs).toBeCloseTo(1105 / 48, 9);
    // a bar later than milestone 6b's -62.362 and -85.382
    expect(formatOffset(setup.wavOffsetMs)).toBe("826.515 ms");
    expect(formatOffset(setup.originalOffsetMs)).toBe("803.494 ms");
  });

  // real_a with the owner's +7 ms anchor nudge from its edit log, checked by ear in a chart editor
  // with the mp3: about +790 ms with the music at measure 1 (the 2-beat pickup at measure 1.5), and
  // about -92 ms with it at measure 0. the panel showed +819.514 / +796.494 and -69.362 / -92.382,
  // the last digit is the rounding of an anchor the report keeps to 3 decimals
  describe("real_a with its anchor nudged", () => {
    const map = [seg(119.521, 134213.979, 270.0038, 951.238 + 7)];
    const meters = [meter(119.521, 134213.979, 4)];
    const source = { ...MP3, duration_ms: 137024 };

    it("puts the music at measure 1 with the pickup halfway into it", () => {
      const { grid, setup } = setupOf(map, meters, source, chartStartOf(119.521, 490.779, 1));
      expect(setup.firstMeasure).toBe(1);
      expect(setup.firstMeasureMs).toBeCloseTo(69.362, 2);
      expect(setup.wavOffsetMs).toBeCloseTo(819.514, 2);
      expect(setup.originalOffsetMs).toBeCloseTo(796.494, 2);
      // the first tracked beat, two beats of 270 into measure 1
      const bar = grid.regions[0]?.barMs ?? 0;
      expect(1 + (490.779 - setup.firstMeasureMs) / bar).toBeCloseTo(1.5, 1);
    });

    it("puts it at measure 0 with the setting at 0", () => {
      const { setup } = setupOf(map, meters, source, chartStartOf(119.521, 490.779, 0));
      expect(setup.firstMeasure).toBe(0);
      expect(setup.wavOffsetMs).toBeCloseTo(-69.362, 2);
      expect(setup.originalOffsetMs).toBeCloseTo(-92.382, 2);
    });
  });

  it("flips the offsets for an editor where a positive offset starts the song earlier", () => {
    const later = setupOf(MAP, METER).setup;
    const earlier = setupOf(MAP, METER, MP3, undefined, "earlier").setup;

    expect(earlier.offsetSign).toBe("earlier");
    expect(earlier.wavOffsetMs).toBe(-later.wavOffsetMs);
    expect(earlier.originalOffsetMs).toBe(-later.originalOffsetMs);
    expect(earlier.measureZeroMs).toBe(later.measureZeroMs);
    // measure 0 at -1500 ms, so the song starts 1500 ms early in that convention
    expect(formatOffset(earlier.wavOffsetMs)).toBe("-1500.000 ms");
    expect(setupText(earlier, 2).split("\n")[0]).toBe("offset with the wav from ffmpeg: -1500.000 ms");
  });

  it("shows a change that isn't on beat 1 with its beat, as mid-measure", () => {
    // 150 bpm from 15000, two beats into the bar at 14000, its own bars from 15800
    const map = [seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15800)];
    const { setup } = setupOf(map, []);
    const change = setup.rows.find((r) => r.kind === "bpm" && r.bpm === 150);

    expect(change).toMatchObject({ measure: 8, beat: 2 });
    expect(rowText(change as ChartRow, 2)).toBe("m.8 · beat 3 · 150.00 bpm · mid-measure");
    // the bar it sits in is still a full 4/4, two beats at each tempo
    expect(setup.rows.filter((r) => r.kind === "signature")).toHaveLength(1);
  });

  it("shows a change on a fractional beat as a fraction", () => {
    // the second grid doesn't carry on from the first, its first line is 2.2 beats into the bar
    // at 14000 and its own bars start two beats later
    const map = [seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15900)];
    const { setup } = setupOf(map, []);
    const change = setup.rows.find((r) => r.kind === "bpm" && r.bpm === 150) as ChartRow;

    expect(change.measure).toBe(8);
    expect(change.beat).toBeCloseTo(2.2, 9);
    expect(rowText(change, 2)).toBe("m.8 · beat 3 + 1/5 · 150.00 bpm · mid-measure");
  });

  it("doesn't make a cut bar of a handover a fraction of a ms off a whole beat", () => {
    // what the 120 -> 150 click track gives, two fits that meet 0.77 ms off the first one's beat
    const map = [seg(709.546, 48709.274, 120.0011, 708.946), seg(48709.274, 59000, 150, 48709.274)];
    const { setup } = setupOf(map, []);
    expect(brief(setup.rows)).toEqual([
      [0, 0, "4/4"],
      [0, 0, 120.0011],
      [25, 0, 150],
    ]);
  });

  it("uses the same measure numbers as the timeline's bar labels", () => {
    const cases: [TempoSegment[], MeterSegment[], ChartStart][] = [
      [MAP, METER, chartStartOf(400, 499.3)],
      [[seg(1800, 59000, 120, 2300)], [], chartStartOf(1800, 1799.3)],
      [[seg(8000, 59000, 120, 8000)], [], chartStartOf(8000, 7999.3)],
      [[seg(8000, 59000, 120, 8000)], [], chartStartOf(8000, 7999.3, 0)],
      [[seg(0, 15000, 120, 0), seg(15000, 59000, 150, 15800)], [], chartStartOf(0, 0)],
    ];
    for (const [map, meters, start] of cases) {
      const { grid, setup } = setupOf(map, meters, MP3, start);
      for (const row of setup.rows) {
        const at = measureStart(grid, row.measure);
        // the bar line the timeline draws where the measure starts carries that number. measure 0
        // can start before the audio, there's nothing drawn there
        if (at >= 0) {
          const label = mapLines(grid, at - 1, at + 1).find((l) => l.isBar && Math.abs(l.timeMs - at) < 0.5);
          expect(label?.bar).toBe(row.measure);
        }
        // and a change sits inside its measure
        expect(row.timeMs).toBeGreaterThanOrEqual(at - 1e-6);
        expect(row.timeMs).toBeLessThan(measureStart(grid, row.measure + 1));
      }
      // nothing before measure 0 is numbered on the timeline
      expect(grid.bars.filter((b) => b.timeMs < setup.measureZeroMs - 0.5).every((b) => b.bar < 0)).toBe(true);
    }
  });

  it("copies the same lines the panel shows, one change per line", () => {
    const { setup } = setupOf(MAP, METER);
    const lines = setupText(setup, 2).trimEnd().split("\n");

    expect(lines.slice(0, 2)).toEqual([
      "offset with the wav from ffmpeg: 1500.000 ms",
      "offset with the original mp3: 1476.979 ms",
    ]);
    expect(lines.slice(2)).toEqual(setup.rows.map((r) => rowText(r, 2)));
    expect(lines.slice(2)).toEqual(["m.0 · 4/4", "m.0 · 120.00 bpm", "m.9 · 150.00 bpm", "m.13 · 7/4"]);
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
      [16500, "m.9 · 150.00 bpm"],
      [22900, "m.13 · 7/4"],
    ]);
  });

  it("puts a tempo and a meter change on the same line into one label", () => {
    const map = [seg(400, 16500, 120, 500), seg(16500, 59000, 150, 16500)];
    const { setup } = setupOf(map, [meter(400, 16500, 4), meter(16500, 59000, 3)]);
    expect(changeLabels(setup, 2).map((l) => l.text)).toEqual(["m.9 · 3/4 · 150.00 bpm"]);
  });
});

describe("wavName", () => {
  it("names the converted wav after the song without writing over a wav", () => {
    expect(wavName("song.mp3")).toBe("song.wav");
    expect(wavName("【音源】テスト曲.mp3")).toBe("【音源】テスト曲.wav");
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

// real_d as the analysis gives it now: 291.99 bpm (twice the chart's 146) with the anchor on
// the first beat at 8078.498 ms, the trim at 8068.5 ms and the mp3's 1105 samples at 48 khz. the
// owner's chart, by ear at 146: -6475 ms with the mp3, measure 1 on the first downbeat. the grid sits
// about 17 ms earlier than that, see docs/decisions.md (real_d)
describe("chartSetup on real_d", () => {
  const REAL_D: AudioSource = { ...MP3, filename: "real_d.mp3", duration_ms: 135407.167 };
  const map = (bpm: number) => [seg(8068.5, 133707.917, bpm, 8078.498)];
  const start = chartStartOf(8068.5, 8081.493);

  it("puts measure 1 on the first beat at 291.99", () => {
    const { setup } = setupOf(map(291.9899), [meter(8068.5, 133707.917, 4)], REAL_D, start);
    expect(setup.firstMeasureMs).toBeCloseTo(8078.498, 3);
    expect(setup.originalOffsetMs).toBeCloseTo(-7279.573, 2);
  });

  it("keeps measure 1 there with the bpm halved, within the bias of the chart's offset", () => {
    const { setup } = setupOf(map(145.99495), [meter(8068.5, 133707.917, 4)], REAL_D, start);
    expect(setup.firstMeasureMs).toBeCloseTo(8078.498, 3);
    expect(setup.originalOffsetMs).toBeCloseTo(-6457.627, 2);
    expect(Math.abs(setup.originalOffsetMs - -6475)).toBeLessThan(20);
    expect(brief(setup.rows)).toEqual([
      [0, 0, "4/4"],
      [0, 0, 145.99495],
    ]);
  });
});
