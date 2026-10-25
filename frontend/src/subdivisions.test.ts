import { describe, expect, it } from "vitest";
import { divisionAt, divisionText, feelKindText } from "./subdivisions";
import type { SubdivisionSection } from "./types/timingReport";

const section = (kind: SubdivisionSection["kind"], division: number, ratio = 2): SubdivisionSection => ({
  start_ms: 1000,
  end_ms: 5000,
  kind,
  ratio,
  division,
  grid_bpm: 292,
  score: 0.8,
});

describe("divisionAt", () => {
  it("is the report's division at the bpm it was read on", () => {
    expect(divisionAt(12, 292, 292)).toBe(12);
    expect(divisionAt(16, 292, 292)).toBe(16);
    expect(divisionAt(24, 292, 292)).toBe(24);
  });

  it("doubles with the bpm halved, the notes are twice as fine in its beats", () => {
    // a swung 8th at 292 is a swung 16th at 146, on triplet 16ths
    expect(divisionAt(12, 292, 146)).toBe(24);
    expect(divisionAt(16, 292, 146)).toBe(32);
  });

  it("works out a doubled bpm", () => {
    // swing at 2/3 of a 146 beat is 4/3 of a 292 beat, still thirds
    expect(divisionAt(12, 146, 292)).toBe(12);
    // a gallop at 1/2 and 3/4 of a 146 beat is at 1 and 1.5 beats of 292, halves
    expect(divisionAt(16, 146, 292)).toBe(8);
  });

  it("takes a bpm a hair off the ratio as the ratio", () => {
    expect(divisionAt(12, 291.9899, 145.99495)).toBe(24);
  });

  it("gives up on a bpm that isn't a small ratio", () => {
    expect(divisionAt(12, 292, 200.7)).toBeNull();
    expect(divisionText(null)).toBe("no simple division at this bpm");
    expect(divisionText(24)).toBe("1/24");
  });
});

describe("feelKindText", () => {
  it("names each kind, triplet based or not", () => {
    expect(feelKindText(section("swing", 12, 1.98))).toBe("swing 1.98:1");
    expect(feelKindText(section("gallop", 16))).toBe("gallop, 8th-16th-16th");
    expect(feelKindText(section("gallop", 24, 4))).toBe("gallop on triplets");
    expect(feelKindText(section("reverse_gallop", 16))).toBe("reverse gallop, 16th-16th-8th");
    expect(feelKindText(section("reverse_gallop", 24, 4))).toBe("reverse gallop on triplets");
  });
});
