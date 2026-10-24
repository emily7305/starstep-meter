import { describe, expect, it } from "vitest";
import { decidedText, suggestionKindText } from "./components/SuggestionList";
import type { NotationSuggestion } from "./types/timingReport";

function suggestion(status: NotationSuggestion["status"], kind: NotationSuggestion["kind"] = "half"): NotationSuggestion {
  return { start_ms: 1000, end_ms: 9000, kind, suggested_bpm: 87, grid_bpm: 174, score: 0.82, status };
}

describe("suggestionKindText", () => {
  it("names each kind the way a chart would talk about it", () => {
    expect(suggestionKindText("half")).toBe("half time");
    expect(suggestionKindText("double")).toBe("double time");
    expect(suggestionKindText("fold")).toBe("fold into neighbour");
  });
});

describe("decidedText", () => {
  it("counts applied before dismissed", () => {
    const list = [suggestion("dismissed"), suggestion("applied"), suggestion("dismissed"), suggestion("open")];
    expect(decidedText(list)).toBe("1 applied, 2 dismissed");
  });

  it("leaves out the kind that has none", () => {
    expect(decidedText([suggestion("applied"), suggestion("applied")])).toBe("2 applied");
    expect(decidedText([suggestion("dismissed")])).toBe("1 dismissed");
  });

  it("is empty when nothing was decided, whether or not there are open ones", () => {
    expect(decidedText([])).toBe("");
    expect(decidedText([suggestion("open"), suggestion("open", "fold")])).toBe("");
  });
});
