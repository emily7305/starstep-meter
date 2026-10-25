import { afterEach, describe, expect, it, vi } from "vitest";
import { bubblePosition, markTourSeen, type Rect, SONG_STEPS, START_STEPS, stepsFor, tourSeen, tourTarget } from "./tour";

const VIEWPORT = { width: 1000, height: 800 };
const BUBBLE = { width: 300, height: 150 };

function rect(over: Partial<Rect> = {}): Rect {
  return { top: 100, left: 200, width: 400, height: 50, ...over };
}

describe("the steps", () => {
  it("has the picker on the start screen and the four parts of an analyzed song after it", () => {
    expect(START_STEPS.map((step) => step.id)).toEqual(["upload"]);
    expect(SONG_STEPS.map((step) => step.id)).toEqual(["card", "timeline", "loupe", "setup"]);
    expect(stepsFor("start")).toBe(START_STEPS);
    expect(stepsFor("song")).toBe(SONG_STEPS);
  });

  it("keeps the copy lowercase and plain", () => {
    for (const step of [...START_STEPS, ...SONG_STEPS]) {
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
    expect(bubblePosition(null, BUBBLE, VIEWPORT)).toEqual({ top: 325, left: 350, placement: "center", arrow: null });
  });

  it("goes beside a button, centred on it, with the arrow at its middle", () => {
    // a 160 x 44 button, the bubble 14 px to its right
    const button = rect({ top: 300, left: 100, width: 160, height: 44 });
    expect(bubblePosition(button, BUBBLE, VIEWPORT)).toEqual({ top: 247, left: 274, placement: "right", arrow: 75 });
  });

  it("keeps the arrow on the target when the bubble is pushed off its middle", () => {
    // near the top the bubble is clamped to the margin, the arrow follows the button down to it
    const button = rect({ top: 10, left: 100, width: 160, height: 44 });
    const place = bubblePosition(button, BUBBLE, VIEWPORT);
    expect(place.top).toBe(16);
    expect(place.arrow).toBe(16);
  });

  it("goes below a band across the page, pointing a little way into it", () => {
    const band = rect({ top: 100, left: 16, width: 968, height: 200 });
    // 100 + 200 + 14, and the arrow 48 px into the band
    expect(bubblePosition(band, BUBBLE, VIEWPORT)).toEqual({ top: 314, left: 32, placement: "below", arrow: 32 });
  });

  it("goes above when there is no room below or beside", () => {
    const band = rect({ top: 600, left: 16, width: 968, height: 100 });
    expect(bubblePosition(band, BUBBLE, VIEWPORT)).toMatchObject({ top: 436, placement: "above" });
  });

  it("goes on the left of something at the right edge with no room under or over it", () => {
    const tall = rect({ top: 50, left: 700, width: 280, height: 700 });
    expect(bubblePosition(tall, BUBBLE, VIEWPORT)).toMatchObject({ left: 386, placement: "left" });
  });

  it("sits over a target that fills the screen rather than leave it", () => {
    const huge = rect({ top: 20, left: 10, width: 980, height: 760 });
    const place = bubblePosition(huge, BUBBLE, VIEWPORT);
    expect(place.placement).toBe("below");
    expect(place.top).toBe(VIEWPORT.height - 16 - BUBBLE.height);
  });

  it("centers when the target is entirely off screen", () => {
    const centered = { top: 325, left: 350, placement: "center", arrow: null };
    expect(bubblePosition(rect({ top: -300, height: 100 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ top: 900 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ left: -500, width: 400 }), BUBBLE, VIEWPORT)).toEqual(centered);
    expect(bubblePosition(rect({ left: 1200 }), BUBBLE, VIEWPORT)).toEqual(centered);
  });

  it("treats a target that only touches the viewport edge as off screen", () => {
    expect(bubblePosition(rect({ top: -50, height: 50 }), BUBBLE, VIEWPORT).placement).toBe("center");
    expect(bubblePosition(rect({ top: 800 }), BUBBLE, VIEWPORT).placement).toBe("center");
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

  it("has seen neither part on a fresh browser", () => {
    stubStorage();
    expect(tourSeen("start")).toBe(false);
    expect(tourSeen("song")).toBe(false);
  });

  it("remembers each part on its own", () => {
    const items = stubStorage();
    markTourSeen("start");
    expect(items.get("starstep.tourSeen")).toBe("1");
    expect(tourSeen("start")).toBe(true);
    expect(tourSeen("song")).toBe(false);
    markTourSeen("song");
    expect(items.get("starstep.tourSeen.song")).toBe("1");
  });

  it("counts a browser that saw the old five-step tour as having seen the start", () => {
    stubStorage({ "starstep.tourSeen": "1" });
    expect(tourSeen("start")).toBe(true);
    expect(tourSeen("song")).toBe(false);
  });

  it("only counts the stored 1", () => {
    stubStorage({ "starstep.tourSeen.song": "0" });
    expect(tourSeen("song")).toBe(false);
  });

  it("is not seen when reading throws, and writing doesn't throw", () => {
    stubBrokenStorage();
    expect(tourSeen("song")).toBe(false);
    expect(() => markTourSeen("song")).not.toThrow();
  });

  it("copes with no storage at all", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(tourSeen("start")).toBe(false);
    expect(() => markTourSeen("start")).not.toThrow();
  });
});
