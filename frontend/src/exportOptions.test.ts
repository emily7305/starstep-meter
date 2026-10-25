import { describe, expect, it } from "vitest";
import { downloadName, exportPath } from "./exportOptions";

describe("exportPath", () => {
  it("asks for the export with or without beats", () => {
    expect(exportPath("abc", { beats: false })).toBe("/api/jobs/abc/export");
    expect(exportPath("abc", { beats: true })).toBe("/api/jobs/abc/export?beats=true");
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
