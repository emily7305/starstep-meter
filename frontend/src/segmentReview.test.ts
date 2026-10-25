import { describe, expect, it } from "vitest";
import { notationScaleOf, reviewSegment, reviewText } from "./segmentReview";
import type { MeterSegment, TempoSegment, TimingReport } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number, source: "auto" | "manual" = "auto", scale = 1): TempoSegment {
  return {
    start_ms: start,
    end_ms: end,
    bpm,
    anchor_ms: anchor,
    confidence: source === "auto" ? 0.9 : null,
    source,
    notation_scale: scale,
    ratio_merged: [],
  };
}

function meter(start: number, end: number, numerator: number, source: "auto" | "manual" = "auto"): MeterSegment {
  return { start_ms: start, end_ms: end, numerator, denominator: 4, confidence: null, source };
}

function report(tempo: TempoSegment[], meters: MeterSegment[], auto: { tempo: TempoSegment[]; meter: MeterSegment[] } | null): TimingReport {
  return {
    schema_version: "2.6",
    source: { filename: "song.mp3", sha256: "0".repeat(64), duration_ms: 140000, sample_rate: 48000, codec: "mp3", decoder_padding_samples: 1105 },
    trim: { start_ms: tempo[0]?.start_ms ?? 0, end_ms: tempo.at(-1)?.end_ms ?? 0 },
    tempo_map: tempo as TimingReport["tempo_map"],
    meter_map: meters,
    sections: [],
    offbeat_runs: [],
    notation_suggestions: [],
    subdivision_sections: [],
    confidence_spans: [],
    cross_check: null,
    auto_result: auto === null ? null : { tempo_map: auto.tempo as TimingReport["tempo_map"], meter_map: auto.meter },
    edits: [],
  };
}

// like real_d: the analysis at 291.99 with the first beat at 8078.498, the old hand-halved segment
// kept its anchor a 146 beat late
const ANALYSIS = { tempo: [seg(8068.5, 133707.9, 291.9899, 8078.498)], meter: [meter(8068.5, 133707.9, 4)] };
const BEAT_146 = 60000 / 145.99495;

describe("reviewSegment", () => {
  it("says a hand-halved segment one beat late has its first beat a beat early in the analysis", () => {
    const stale = report([seg(8068.5, 133707.9, 145.99495, 8078.498 + BEAT_146, "manual")], ANALYSIS.meter, ANALYSIS);
    const review = reviewSegment(stale, 0);
    expect(review).not.toBeNull();
    expect(review?.shiftMs).toBeCloseTo(-BEAT_146, 6);
    expect(review?.shiftBeats).toBeCloseTo(-1, 6);
    // /2 is a notation choice, not a different bpm
    expect(review?.analysisBpm).toBeNull();
    expect(review?.meter).toBeNull();
    expect(reviewText(review!)).toBe("this segment is manual; the new analysis would put its first beat 411.0 ms (1 beat) earlier");
  });

  it("counts a bpm typed close to /2 as the same notation choice", () => {
    const typed = report([seg(8068.5, 133707.9, 146, 8078.498 + 3, "manual")], ANALYSIS.meter, ANALYSIS);
    const review = reviewSegment(typed, 0);
    expect(review?.analysisBpm).toBeNull();
    expect(review?.shiftMs).toBeCloseTo(-3, 6);
    expect(reviewText(review!)).toBe("this segment is manual; the new analysis would put its first beat 3.0 ms earlier");
  });

  it("names the bpm and the meter when those differ too", () => {
    const tempo = [seg(1000, 60000, 150, 1100, "manual")];
    const auto = { tempo: [seg(1000, 60000, 120, 1000)], meter: [meter(1000, 60000, 4)] };
    const review = reviewSegment(report(tempo, [meter(1000, 60000, 3, "manual")], auto), 0);
    expect(review?.analysisBpm).toBe(120);
    expect(review?.meter).toEqual({ here: "3/4", analysis: "4/4" });
    expect(reviewText(review!)).toBe(
      "this segment is manual; the new analysis would put its first beat 100.0 ms (0.25 beats) earlier, has it at 120.00 bpm and has 4/4 where this has 3/4",
    );
  });

  it("takes a whole bar off as the same bar line", () => {
    const bar = 4 * BEAT_146;
    const moved = report([seg(8068.5, 133707.9, 145.99495, 8078.498 + bar, "manual")], ANALYSIS.meter, ANALYSIS);
    expect(reviewSegment(moved, 0)).toBeNull();
  });

  it("has nothing to say about an auto segment, a matching manual one or a report from before 2.6", () => {
    expect(reviewSegment(report(ANALYSIS.tempo, ANALYSIS.meter, ANALYSIS), 0)).toBeNull();
    const same = report([seg(8068.5, 133707.9, 145.99495, 8078.498, "manual")], ANALYSIS.meter, ANALYSIS);
    expect(reviewSegment(same, 0)).toBeNull();
    const old = report([seg(8068.5, 133707.9, 145.99495, 8078.498 + BEAT_146, "manual")], ANALYSIS.meter, null);
    expect(reviewSegment(old, 0)).toBeNull();
  });
});

describe("notationScaleOf", () => {
  it("finds the power of two, exactly for the buttons and within 1% for a typed bpm", () => {
    expect(notationScaleOf(0.5)).toBe(0.5);
    expect(notationScaleOf(146 / 291.9899)).toBe(0.5);
    expect(notationScaleOf(4)).toBe(4);
    expect(notationScaleOf(0.75)).toBeNull();
    expect(notationScaleOf(16)).toBeNull();
  });
});
