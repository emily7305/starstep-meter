import { afterEach, describe, expect, it, vi } from "vitest";
import { bubblePosition, markTourSeen, type Rect, TOUR_STEPS, tourSeen, tourTarget } from "./tour";

const VIEWPORT = { width: 1000, height: 800 };
const BUBBLE = { width: 300, height: 150 };

function rect(over: Partial<Rect> = {}): Rect {
  return { top: 100, left: 200, width: 400, height: 50, ...over };
}

describe("TOUR_STEPS", () => {
  it("has the five steps in order", () => {
    expect(TOUR_STEPS.map((step) => step.id)).toEqual(["upload", "card", "timeline", "loupe", "setup"]);
  });

  it("keeps the copy lowercase and plain", () => {
    for (const step of TOUR_STEPS) {
      expect(step.title).toBe(step.title.toLowerCase());
      expect(step.text).toBe(step.text.toLowerCase());
      expect(step.title + step.text).not.toContain("!");
    }
  });
});

describe("tourTarget", () => {
  it("selects the element marked with the step id", () => {
    expect(tourTarget("upload")).toBe('[data-tour="upload"]');
    expect(tourTarget("setup")).toBe('[data-tour="setup"]');
  });
});

describe("bubblePosition", () => {
  it("centers the bubble when there is no target", () => {
    expect(bubblePosition(null, BUBBLE, VIEWPORT)).toEqual({ top: 325, left: 350, placement: "center" });
  });

  it("goes below the target, aligned with its left edge", () => {
    expect(bubblePosition(rect(), BUBBLE, VIEWPORT)).toEqual({ top: 162, left: 200, placement: "below" });
  });

  it("stays below while the bubble ends exactly at the bottom margin", () => {
    // 572 + 50 + 12 = 634, and 634 + 150 = 784 = 800 - 16
    expect(bubblePosition(rect({ top: 572 }), BUBBLE, VIEWPORT).placement).toBe("below");
  });

  it("goes above when there is no room below", () => {
    expect(bubblePosition(rect({ top: 573 }), BUBBLE, VIEWPORT)).toEqual({ top: 411, left: 200, placement: "above" });
    expect(bubblePosition(rect({ top: 700 }), BUBBLE, VIEWPORT)).toEqual({ top: 538, left: 200, placement: "above" });
  });

  it("clamps below into the viewport when neither side has room", () => {
    const tall = rect({ top: 100, height: 650 });
    expect(bubblePosition(tall, BUBBLE, VIEWPORT)).toEqual({ top: 634, left: 200, placement: "below" });
  });

  it("clamps the left edge to the margin", () => {
    expect(bubblePosition(rect({ left: 5 }), BUBBLE, VIEWPORT).left).toBe(16);
    expect(bubblePosition(rect({ left: -120, width: 400 }), BUBBLE, VIEWPORT).left).toBe(16);
  });

  it("clamps the right edge so the bubble stays inside", () => {
    // 1000 - 16 - 300
    expect(bubblePosition(rect({ left: 900, width: 80 }), BUBBLE, VIEWPORT).left).toBe(684);
  });

  it("uses the margin as left when the bubble is wider than the room", () => {
    expect(bubblePosition(rect({ left: 300 }), { width: 980, height: 150 }, VIEWPORT).left).toBe(16);
  });

  it("centers when the target is entirely off screen", () => {
    const centered = { top: 325, left: 350, placement: "center" };
    expect(bubblePosition(rect({ top: -300, height: 100 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ top: 900 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ left: -500, width: 400 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ left: 1200 }), BUBBLE, VIEWPORT)).toEqual(centered);
  });

  it("treats a target that only touches the viewport edge as off screen", () => {
    expect(bubblePosition(rect({ top: -50, height: 50 }), BUBBLE, VIEWPORT).placement).toBe("center");
    expect(bubblePosition(rect({ top: 800 }), BUBBLE, VIEWPORT).placement).toBe("center");
  });

  it("still anchors to a target that is partly on screen", () => {
    expect(bubblePosition(rect({ top: -20, height: 100 }), BUBBLE, VIEWPORT)).toEqual({
      top: 92,
      left: 200,
      placement: "below",
    });
  });

  it("takes its own margin and gap", () => {
    expect(bubblePosition(rect({ left: 5 }), BUBBLE, VIEWPORT, 40, 20)).toEqual({ top: 170, left: 40, placement: "below" });
  });
});

// storage is a global in the browser, the tests swap it for a fake
function stubStorage(initial: Record<string, string> = {}) {
  const items = new Map(Object.entries(initial));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => void items.set(key, value),
  });
  return items;
}

function stubBrokenStorage() {
  const fail = () => {
    throw new Error("storage is off");
  };
  vi.stubGlobal("localStorage", { getItem: fail, setItem: fail });
}

describe("tour storage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("has not been seen on a fresh browser", () => {
    stubStorage();
    expect(tourSeen()).toBe(false);
  });

  it("remembers the tour once it is marked", () => {
    const items = stubStorage();
    markTourSeen();
    expect(items.get("starstep.tourSeen")).toBe("1");
    expect(tourSeen()).toBe(true);
  });

  it("only counts the stored 1", () => {
    stubStorage({ "starstep.tourSeen": "0" });
    expect(tourSeen()).toBe(false);
    stubStorage({ "starstep.tourSeen": "1" });
    expect(tourSeen()).toBe(true);
  });

  it("is not seen when reading throws", () => {
    stubBrokenStorage();
    expect(tourSeen()).toBe(false);
  });

  it("does nothing when writing throws", () => {
    stubBrokenStorage();
    expect(() => markTourSeen()).not.toThrow();
  });

  it("copes with no storage at all", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(tourSeen()).toBe(false);
    expect(() => markTourSeen()).not.toThrow();
  });
});
