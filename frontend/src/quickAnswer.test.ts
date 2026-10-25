import { describe, expect, it } from "vitest";
import { formatOffset, setupText } from "./chartSetup";
import { changesLine, quickAnswer, quickText, setupFor } from "./quickAnswer";
import { chartStartOf } from "./tempoMap";
import type { AudioSource, ConfidenceSpan, MeterSegment, TempoSegment, TimingReport } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number, source: "auto" | "manual" = "auto"): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: 1, source, ratio_merged: [] };
}

function meter(start: number, end: number, numerator: number): MeterSegment {
  return { start_ms: start, end_ms: end, numerator, denominator: 4, confidence: 1, source: "auto" };
}

const MP3: AudioSource = {
  filename: "song.mp3",
  sha256: "0".repeat(64),
  duration_ms: 137024,
  sample_rate: 48000,
  codec: "mp3",
  decoder_padding_samples: 1105,
};

function report(tempo: TempoSegment[], meters: MeterSegment[], source = MP3, spans: ConfidenceSpan[] = []): TimingReport {
  return {
    schema_version: "2.5",
    source,
    trim: { start_ms: tempo[0]?.start_ms ?? 0, end_ms: tempo.at(-1)?.end_ms ?? 0 },
    tempo_map: tempo as TimingReport["tempo_map"],
    meter_map: meters,
    sections: [],
    offbeat_runs: [],
    notation_suggestions: [],
    subdivision_sections: [],
    confidence_spans: spans,
    cross_check: null,
    edits: [],
  };
}

function span(start: number, end: number, low: boolean): ConfidenceSpan {
  return { start_ms: start, end_ms: end, confidence: low ? 0.3 : 1, residual_share: low ? 0.3 : 1, agreement: null, low };
}

// real_a's map from its report, one tempo, 4/4 all through
const STEADY = report([seg(119.521, 134213.979, 270.0038, 951.238)], [meter(119.521, 134213.979, 4)]);
// 120 bpm, 150 from bar 8, 7/4 four bars later
const CHANGING = report(
  [seg(400, 16500, 120, 500), seg(16500, 59000, 150, 16500)],
  [meter(400, 22900, 4), meter(22900, 59000, 7)],
  { ...MP3, duration_ms: 60000 },
);
const WAV: AudioSource = { ...MP3, filename: "click.wav", codec: "pcm_f32le", decoder_padding_samples: 0 };

describe("quickAnswer", () => {
  it("matches the chart setup list and the report on a constant tempo song", () => {
    const q = quickAnswer(STEADY);
    const setup = setupFor(STEADY);
    expect(q).not.toBeNull();
    if (q === null || setup === null) return;

    expect(q.bpm).toBe(STEADY.tempo_map[0]?.bpm);
    expect([q.numerator, q.denominator]).toEqual([4, 4]);
    expect(q.wavOffsetMs).toBe(setup.wavOffsetMs);
    expect(q.originalOffsetMs).toBe(setup.originalOffsetMs);
    // measure 1 on the bar line at 62.362 ms, measure 0 a bar before the file starts
    expect(formatOffset(q.wavOffsetMs)).toBe("826.515 ms");
    expect(formatOffset(q.originalOffsetMs as number)).toBe("803.494 ms");
    expect(changesLine(q)).toBeNull();
    // the copied card carries the same offsets as the copied list
    const list = setupText(setup, 2);
    for (const line of quickText(q, 2).split("\n").filter((l) => l.startsWith("offset"))) {
      expect(list).toContain(line.slice(line.indexOf(":")));
    }
  });

  it("says plainly when the song changes speed or time signature", () => {
    const q = quickAnswer(CHANGING);
    expect(q).not.toBeNull();
    if (q === null) return;

    expect(q.bpm).toBe(120);
    expect(q.bpmChanges).toBe(1);
    expect(q.signatureChanges).toBe(1);
    expect(changesLine(q)).toBe("this song changes speed once and changes time signature once");
    expect(quickText(q, 2)).toContain("bpm at the start: 120.00");
    expect(quickText(q, 2)).toContain("time signature: 4/4");
  });

  it("counts every change in the list", () => {
    const tempo = [seg(400, 16500, 120, 500), seg(16500, 32500, 150, 16500), seg(32500, 59000, 180, 32500)];
    const q = quickAnswer(report(tempo, [], { ...MP3, duration_ms: 60000 }));
    expect(q?.bpmChanges).toBe(2);
    expect(changesLine(q as NonNullable<typeof q>)).toBe("this song changes speed 2 times");
  });

  it("has no line for the original file when it has no decoder padding", () => {
    const q = quickAnswer(report(STEADY.tempo_map, STEADY.meter_map, WAV));
    expect(q).not.toBeNull();
    if (q === null) return;

    expect(q.originalOffsetMs).toBeNull();
    expect(quickText(q, 2)).not.toContain("original");
    expect(quickText(q, 2)).toContain("offset if you load the wav made with ffmpeg: 826.515 ms");
  });

  it("warns once when parts were hard to read, only under segments the analysis made", () => {
    const low = report(STEADY.tempo_map, STEADY.meter_map, MP3, [span(1000, 5000, false), span(5000, 9000, true)]);
    expect(quickAnswer(low)?.hardToRead).toBe(true);
    expect(quickText(quickAnswer(low) as NonNullable<ReturnType<typeof quickAnswer>>, 2)).toContain(
      "parts of this song were hard to read, check the shaded areas",
    );
    expect(quickAnswer(STEADY)?.hardToRead).toBe(false);
    const edited = report([{ ...(STEADY.tempo_map[0] as TempoSegment), source: "manual" }], STEADY.meter_map, MP3, [
      span(5000, 9000, true),
    ]);
    expect(quickAnswer(edited)?.hardToRead).toBe(false);
  });

  it("follows the music start setting the same way the list does", () => {
    const at0 = setupFor(STEADY, chartStartOf(STEADY.trim.start_ms, null, 0));
    const q = quickAnswer(STEADY, at0);
    expect(q?.wavOffsetMs).toBe(at0?.wavOffsetMs);
    expect(formatOffset(q?.wavOffsetMs as number)).toBe("-62.362 ms");
  });

  it("shows more decimals when asked", () => {
    const q = quickAnswer(STEADY) as NonNullable<ReturnType<typeof quickAnswer>>;
    expect(quickText(q, 2)).toContain("bpm: 270.00");
    expect(quickText(q, 4)).toContain("bpm: 270.0038");
  });
});
