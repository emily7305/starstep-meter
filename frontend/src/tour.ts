export interface TourStep {
  id: "upload" | "card" | "timeline" | "loupe" | "setup";
  title: string;
  text: string;
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: "upload",
    title: "load a song",
    text: "drop a song anywhere on the page, or press choose a song. it's analyzed on this machine and stays in data/.",
  },
  {
    id: "card",
    title: "for your chart",
    text: "the bpm, the offset and the time signature to type into a chart editor. it shows up above the timeline once a song is analyzed.",
  },
  {
    id: "timeline",
    title: "the whole song",
    text: "waveform, beat grid and bar numbers. click to move the playhead, the wheel scrolls sideways, ctrl+wheel zooms, drag near an edge to keep going.",
  },
  {
    id: "loupe",
    title: "zoomed view",
    text: "a few ms around the playhead, drawn from the wav itself. the grid line should sit on the attack.",
  },
  {
    id: "setup",
    title: "chart setup",
    text: "the offset and every bpm and time signature change by measure, in the order to type them in.",
  },
];

// the page marks its targets with data-tour so the tour doesn't depend on class names
export function tourTarget(id: TourStep["id"]): string {
  return `[data-tour="${id}"]`;
}

const TOUR_KEY = "starstep.tourSeen";

// storage can be off or throw, then the tour just shows again next visit
export function tourSeen(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === "1";
  } catch {
    return false;
  }
}

export function markTourSeen(): void {
  try {
    localStorage.setItem(TOUR_KEY, "1");
  } catch {
    // it just won't be remembered
  }
}

// viewport coordinates, like getBoundingClientRect
export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface BubblePosition {
  top: number;
  left: number;
  placement: "below" | "above" | "center";
}

// a range too small for the bubble ends up at low
function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(value, high));
}

function offScreen(target: Rect, viewport: Size): boolean {
  return (
    target.top + target.height <= 0 ||
    target.top >= viewport.height ||
    target.left + target.width <= 0 ||
    target.left >= viewport.width
  );
}

export function bubblePosition(target: Rect | null, bubble: Size, viewport: Size, margin = 16, gap = 12): BubblePosition {
  if (target === null || offScreen(target, viewport)) {
    return {
      top: (viewport.height - bubble.height) / 2,
      left: (viewport.width - bubble.width) / 2,
      placement: "center",
    };
  }

  const left = clamp(target.left, margin, viewport.width - margin - bubble.width);
  const below = target.top + target.height + gap;
  if (below + bubble.height <= viewport.height - margin) return { top: below, left, placement: "below" };

  const above = target.top - gap - bubble.height;
  if (above >= margin) return { top: above, left, placement: "above" };

  // no room on either side (a tall target), sit on top of it rather than leave the screen
  return { top: clamp(below, margin, viewport.height - margin - bubble.height), left, placement: "below" };
}
