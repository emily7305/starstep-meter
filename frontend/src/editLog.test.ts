import { describe, expect, it } from "vitest";
import { editChanges, editLabel } from "./editLog";
import type { Edit } from "./types/timingReport";

const AT = "2026-10-25T10:00:00Z";

describe("editChanges", () => {
  it("reads a single value with its unit", () => {
    const edit: Edit = { field: "tempo_map/0/anchor_ms", old: 136.774, new: 139.774, timestamp: AT };

    expect(editLabel(edit)).toBe("tempo_map/0/anchor_ms");
    expect(editChanges(edit)).toEqual([{ path: "", old: "136.774 ms", new: "139.774 ms" }]);
  });

  it("splits a segment entry into its changed values", () => {
    const edit: Edit = {
      field: "tempo_map/1",
      old: { bpm: 200, confidence: 0.98, source: "auto" },
      new: { bpm: 400, confidence: null, source: "manual" },
      timestamp: AT,
    };

    expect(editLabel(edit)).toBe("tempo_map/1");
    expect(editChanges(edit)).toEqual([
      { path: "bpm", old: "200 bpm", new: "400 bpm" },
      { path: "confidence", old: "0.980", new: "–" },
      { path: "source", old: "auto", new: "manual" },
    ]);
  });

  it("names both places an applied suggestion touched", () => {
    const seg = { start_ms: 0, end_ms: 1, bpm: 130, anchor_ms: 0, confidence: 1, source: "auto", ratio_merged: [] };
    const edit: Edit = {
      field: "",
      old: { tempo_map: [seg], "notation_suggestions/0/status": "open" },
      new: { tempo_map: [seg, seg, seg], "notation_suggestions/0/status": "applied" },
      timestamp: AT,
    };

    expect(editLabel(edit)).toBe("tempo_map + notation_suggestions/0/status");
    expect(editChanges(edit)).toEqual([
      { path: "tempo_map", old: "1 segment", new: "3 segments" },
      { path: "notation_suggestions/0/status", old: "open", new: "applied" },
    ]);
  });

  it("keeps meter numbers plain", () => {
    const edit: Edit = {
      field: "meter_map/1",
      old: { numerator: 7, confidence: 1, source: "auto" },
      new: { numerator: 3, confidence: null, source: "manual" },
      timestamp: AT,
    };

    expect(editChanges(edit)[0]).toEqual({ path: "numerator", old: "7", new: "3" });
  });

  it("reads entries from before one entry per change the same as ever", () => {
    // milestone 2 logged the offset under its old name
    const edit: Edit = { field: "beat_offset_ms", old: 2000, new: 2120.5, timestamp: AT };

    expect(editChanges(edit)).toEqual([{ path: "", old: "2000.000 ms", new: "2120.500 ms" }]);
  });
});
