export interface TourStep {
  id: "upload" | "card" | "timeline" | "loupe" | "setup";
  title: string;
  text: string;
}

// the start screen has only the picker, the rest of the page shows up once a song is analyzed
export type TourScreen = "start" | "song";

export const START_STEPS: TourStep[] = [
  {
    id: "upload",
    title: "load a song",
    text: "press choose a song, or drop one anywhere on the page. it's analyzed on this machine and stays in data/. no song at hand? try with a demo.",
  },
];

export const SONG_STEPS: TourStep[] = [
  {
    id: "card",
    title: "for your chart",
    text: "the bpm, the offset and the time signature to type into a chart editor.",
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

export function stepsFor(screen: TourScreen): TourStep[] {
  return screen === "start" ? START_STEPS : SONG_STEPS;
}

// the page marks its targets with data-tour so the tour doesn't depend on class names
export function tourTarget(id: TourStep["id"]): string {
  return `[data-tour="${id}"]`;
}

// the start key is the one the five-step tour of milestone 7 used, so it isn't shown again
const TOUR_KEYS: Record<TourScreen, string> = { start: "starstep.tourSeen", song: "starstep.tourSeen.song" };

// storage can be off or throw, then the tour just shows again next visit
export function tourSeen(screen: TourScreen): boolean {
  try {
    return localStorage.getItem(TOUR_KEYS[screen]) === "1";
  } catch {
    return false;
  }
}

export function markTourSeen(screen: TourScreen): void {
  try {
    localStorage.setItem(TOUR_KEYS[screen], "1");
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

export type Placement = "right" | "below" | "above" | "left" | "center";

export interface BubblePosition {
  top: number;
  left: number;
  placement: Placement;
  // where the arrow sits along the bubble's edge that faces the target, px from its top or left
  arrow: number | null;
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

// the arrow keeps clear of the bubble's rounded corners
const ARROW_INSET = 16;
// on a wide target the arrow points this far in from its left edge, not at its middle
const WIDE_POINT = 48;

// beside the target when there's room (a button), else below or above it (a band across the page),
// else on its left. the arrow points at the target from whichever side faces it
export function bubblePosition(target: Rect | null, bubble: Size, viewport: Size, margin = 16, gap = 14): BubblePosition {
  if (target === null || offScreen(target, viewport)) {
    return {
      top: (viewport.height - bubble.height) / 2,
      left: (viewport.width - bubble.width) / 2,
      placement: "center",
      arrow: null,
    };
  }
  const centerY = target.top + target.height / 2;
  const pointX = target.left + Math.min(target.width / 2, WIDE_POINT);
  const vertical = (left: number, placement: Placement): BubblePosition => {
    const top = clamp(centerY - bubble.height / 2, margin, viewport.height - margin - bubble.height);
    return { top, left, placement, arrow: clamp(centerY - top, ARROW_INSET, bubble.height - ARROW_INSET) };
  };
  const horizontal = (top: number, placement: Placement): BubblePosition => {
    const left = clamp(pointX - ARROW_INSET * 2, margin, viewport.width - margin - bubble.width);
    return { top, left, placement, arrow: clamp(pointX - left, ARROW_INSET, bubble.width - ARROW_INSET) };
  };

  const right = target.left + target.width + gap;
  if (right + bubble.width <= viewport.width - margin) return vertical(right, "right");

  const below = target.top + target.height + gap;
  if (below + bubble.height <= viewport.height - margin) return horizontal(below, "below");

  const above = target.top - gap - bubble.height;
  if (above >= margin) return horizontal(above, "above");

  const left = target.left - gap - bubble.width;
  if (left >= margin) return vertical(left, "left");

  // no room on any side (a tall, wide target), sit over it rather than leave the screen
  return horizontal(clamp(below, margin, viewport.height - margin - bubble.height), "below");
}
