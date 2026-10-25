import { describe, expect, it } from "vitest";
import { compensationPresets, downloadName, exportPath, paddingMs, validCompensation } from "./exportOptions";
import type { AudioSource } from "./types/timingReport";

function source(padding: number, sampleRate = 44100): AudioSource {
  return { filename: "song.mp3", sha256: "0".repeat(64), duration_ms: 1000, sample_rate: sampleRate, codec: "mp3", decoder_padding_samples: padding };
}

describe("compensation presets", () => {
  it("offers the padding of an mp3 next to 0", () => {
    expect(paddingMs(source(1105))).toBe(25.057);
    expect(compensationPresets(source(1105))).toEqual([
      { label: "0 ms", ms: 0 },
      { label: "25.057 ms, 1105 padding samples", ms: 25.057 },
    ]);
  });

  it("goes by the file's own sample rate", () => {
    expect(paddingMs(source(1105, 48000))).toBe(23.021);
    expect(paddingMs(source(1024))).toBe(23.22);
  });

  it("has only 0 for a file without padding", () => {
    expect(compensationPresets(source(0))).toEqual([{ label: "0 ms", ms: 0 }]);
  });

  it("refuses what the server would", () => {
    expect(validCompensation(25.057)).toBe(true);
    expect(validCompensation(-12)).toBe(true);
    expect(validCompensation(1000.5)).toBe(false);
    expect(validCompensation(Number.NaN)).toBe(false);
  });
});

describe("exportPath", () => {
  it("asks for the plain export with or without beats", () => {
    expect(exportPath("abc", { preset: "timing", beats: false, compensationMs: 25 })).toBe("/api/jobs/abc/export");
    expect(exportPath("abc", { preset: "timing", beats: true, compensationMs: 0 })).toBe("/api/jobs/abc/export?beats=true");
  });

  it("puts the compensation on the sonolus preset only", () => {
    expect(exportPath("abc", { preset: "sonolus", beats: true, compensationMs: 0 })).toBe("/api/jobs/abc/export?preset=sonolus");
    expect(exportPath("abc", { preset: "sonolus", beats: false, compensationMs: 25.057 })).toBe(
      "/api/jobs/abc/export?preset=sonolus&decoder_compensation_ms=25.057",
    );
  });
});

describe("downloadName", () => {
  it("takes the utf-8 name over the ascii stand-in", () => {
    const header = "attachment; filename=\"____ 120.timing.json\"; filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88%E6%9B%B2%20120.timing.json";

    expect(downloadName(header, "export.json")).toBe("テスト曲 120.timing.json");
  });

  it("falls back to the plain name, then to the fallback", () => {
    expect(downloadName('attachment; filename="song.timing.json"', "export.json")).toBe("song.timing.json");
    expect(downloadName("attachment; filename*=UTF-8''%E3%83", "x.json")).toBe("x.json");
    expect(downloadName(null, "export.json")).toBe("export.json");
  });
});
