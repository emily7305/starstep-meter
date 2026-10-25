import { describe, expect, it } from "vitest";
import {
  clampZoom,
  EDGE_MAX_PX_PER_S,
  EDGE_PX,
  edgeScrollSpeed,
  MAX_PX_PER_S,
  overviewPeaks,
  scrollKeeping,
  stepZoom,
  visibleWindow,
  wheelScrollPx,
  wheelZoom,
  zoomLabel,
} from "./timelineNav";

const wheel = (deltaY: number, extra: Partial<{ deltaX: number; deltaMode: number; shiftKey: boolean }> = {}) => ({
  deltaX: 0,
  deltaY,
  deltaMode: 0,
  shiftKey: false,
  ...extra,
});

describe("edgeScrollSpeed", () => {
  it("is 0 in the middle of the view", () => {
    expect(edgeScrollSpeed(500, 0, 1000)).toBe(0);
    expect(edgeScrollSpeed(EDGE_PX, 0, 1000)).toBe(0);
  });

  it("scrolls left near the left edge and right near the right edge", () => {
    expect(edgeScrollSpeed(10, 0, 1000)).toBeLessThan(0);
    expect(edgeScrollSpeed(990, 0, 1000)).toBeGreaterThan(0);
  });

  it("gets faster the closer the pointer is to the edge", () => {
    const far = edgeScrollSpeed(1000 - EDGE_PX + 10, 0, 1000);
    const near = edgeScrollSpeed(1000 - 10, 0, 1000);
    expect(near).toBeGreaterThan(far);
    expect(edgeScrollSpeed(1000, 0, 1000)).toBe(EDGE_MAX_PX_PER_S);
  });

  it("keeps the top speed past the edge, so a drag outside the timeline keeps going", () => {
    expect(edgeScrollSpeed(1400, 0, 1000)).toBe(EDGE_MAX_PX_PER_S);
    expect(edgeScrollSpeed(-300, 0, 1000)).toBe(-EDGE_MAX_PX_PER_S);
  });

  it("uses a smaller zone on a narrow view", () => {
    // 90 px wide: a 30 px zone, the middle third stays still
    expect(edgeScrollSpeed(45, 0, 90)).toBe(0);
    expect(edgeScrollSpeed(80, 0, 90)).toBeGreaterThan(0);
  });
});

describe("wheelScrollPx", () => {
  it("turns the vertical wheel into a sideways scroll", () => {
    expect(wheelScrollPx(wheel(100), 800)).toBe(100);
    expect(wheelScrollPx(wheel(-100), 800)).toBe(-100);
  });

  it("takes shift+wheel and a trackpad's sideways swipe sideways too", () => {
    expect(wheelScrollPx(wheel(120, { shiftKey: true }), 800)).toBe(120);
    expect(wheelScrollPx(wheel(3, { deltaX: 40 }), 800)).toBe(40);
  });

  it("counts lines and pages in px", () => {
    expect(wheelScrollPx(wheel(3, { deltaMode: 1 }), 800)).toBe(48);
    expect(wheelScrollPx(wheel(1, { deltaMode: 2 }), 800)).toBe(800);
  });
});

describe("zoom", () => {
  it("zooms in on a wheel up and out on a wheel down, from fit too", () => {
    expect(wheelZoom(0, 10, wheel(-100))).toBeGreaterThan(10);
    expect(wheelZoom(200, 10, wheel(100))).toBeLessThan(200);
  });

  it("goes back to fit at the whole song and stops at the top", () => {
    expect(wheelZoom(10.05, 10, wheel(100))).toBe(0);
    expect(clampZoom(5000, 10)).toBe(MAX_PX_PER_S);
    expect(clampZoom(9, 10)).toBe(0);
  });

  it("doubles and halves on the buttons", () => {
    expect(stepZoom(0, 10, 1)).toBe(20);
    expect(stepZoom(100, 10, 1)).toBe(200);
    expect(stepZoom(100, 10, -1)).toBe(50);
    expect(stepZoom(15, 10, -1)).toBe(0);
  });

  it("keeps the time under the mouse where it was", () => {
    // 12 s under a pointer 300 px into the view, at 100 px/s
    expect(scrollKeeping(12, 100, 300)).toBe(900);
    expect(scrollKeeping(1, 100, 300)).toBe(0);
  });

  it("labels the zoom", () => {
    expect(zoomLabel(0)).toBe("fit");
    expect(zoomLabel(99.6)).toBe("100 px/s");
  });
});

describe("visibleWindow", () => {
  it("is the part of the song in view", () => {
    // 100 s at 100 px/s, 1000 px of view scrolled 2000 px in
    expect(visibleWindow(2000, 1000, 10000, 100000)).toEqual({ startMs: 20000, endMs: 30000 });
  });

  it("is the whole song at fit", () => {
    expect(visibleWindow(0, 1000, 1000, 100000)).toEqual({ startMs: 0, endMs: 100000 });
  });
});

describe("overviewPeaks", () => {
  it("keeps the loudest sample of each column", () => {
    const samples = new Float32Array([0.1, -0.5, 0.2, 0.3, -0.1, 0.9, 0, 0]);
    expect(Array.from(overviewPeaks(samples, 4))).toEqual([0.5, 0.30000001192092896, 0.8999999761581421, 0]);
  });

  it("is empty for no columns", () => {
    expect(overviewPeaks(new Float32Array(10), 0).length).toBe(0);
  });
});
