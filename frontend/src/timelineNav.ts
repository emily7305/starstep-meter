// scrolling and zooming the big timeline: dragging into an edge, the wheel, ctrl+wheel and the
// overview strip. plain functions, Timeline.tsx wires them to wavesurfer

// the zone along each edge where a drag keeps scrolling, and how fast it gets right at the edge.
// 2400 px/s is 24 s of song a second at 100 px/s, tuned by hand, revisit
export const EDGE_PX = 64;
export const EDGE_MAX_PX_PER_S = 2400;
export const MAX_PX_PER_S = 2000;
// one wheel notch is about 100 px of delta in chromium, this makes it about a 15% step
const WHEEL_ZOOM_RATE = 0.0015;
const LINE_PX = 16;

// px per second the view scrolls while a drag sits at x. negative is left, 0 outside the edge
// zones. it grows with the square of how far into the zone the pointer is, so the first few px
// creep and the edge itself races, and past the edge it stays at the top speed
export function edgeScrollSpeed(x: number, left: number, right: number, edgePx = EDGE_PX, maxPxPerS = EDGE_MAX_PX_PER_S): number {
  const width = right - left;
  if (width <= 0) return 0;
  const zone = Math.min(edgePx, width / 3);
  const fromLeft = x - left;
  const fromRight = right - x;
  if (fromLeft < zone && fromLeft <= fromRight) {
    const depth = Math.min(1, (zone - fromLeft) / zone);
    return -maxPxPerS * depth * depth;
  }
  if (fromRight < zone) {
    const depth = Math.min(1, (zone - fromRight) / zone);
    return maxPxPerS * depth * depth;
  }
  return 0;
}

export interface WheelLike {
  deltaX: number;
  deltaY: number;
  deltaMode: number;
  shiftKey: boolean;
}

// how far a wheel event scrolls the timeline sideways, in px. shift turns the vertical wheel
// sideways like everywhere else, a trackpad's own sideways swipe counts as is
export function wheelScrollPx(event: WheelLike, viewWidthPx: number): number {
  const unit = event.deltaMode === 1 ? LINE_PX : event.deltaMode === 2 ? viewWidthPx : 1;
  const sideways = event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY);
  const delta = sideways ? (Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY) : event.deltaY;
  return delta * unit;
}

// the next px/s for a ctrl+wheel step, 0 back at fit. fit is the whole song in the view
export function wheelZoom(currentPxPerS: number, fitPxPerS: number, event: WheelLike): number {
  const unit = event.deltaMode === 1 ? LINE_PX : event.deltaMode === 2 ? 400 : 1;
  const from = currentPxPerS > 0 ? currentPxPerS : fitPxPerS;
  return clampZoom(from * Math.exp(-event.deltaY * unit * WHEEL_ZOOM_RATE), fitPxPerS);
}

// the -/+ buttons halve and double
export function stepZoom(currentPxPerS: number, fitPxPerS: number, direction: 1 | -1): number {
  const from = currentPxPerS > 0 ? currentPxPerS : fitPxPerS;
  return clampZoom(direction > 0 ? from * 2 : from / 2, fitPxPerS);
}

export function clampZoom(pxPerS: number, fitPxPerS: number): number {
  // a hair over fit is fit, otherwise there's a scrollbar with nowhere to go
  if (!(pxPerS > fitPxPerS * 1.01)) return 0;
  return Math.min(MAX_PX_PER_S, pxPerS);
}

// where to scroll so the time under offsetPx (from the view's left edge) stays under it
export function scrollKeeping(timeS: number, pxPerS: number, offsetPx: number): number {
  return Math.max(0, timeS * pxPerS - offsetPx);
}

export interface VisibleWindow {
  startMs: number;
  endMs: number;
}

export function visibleWindow(scrollPx: number, viewWidthPx: number, totalWidthPx: number, durationMs: number): VisibleWindow {
  if (totalWidthPx <= 0 || durationMs <= 0) return { startMs: 0, endMs: durationMs };
  const startMs = (Math.max(0, scrollPx) / totalWidthPx) * durationMs;
  const endMs = (Math.min(totalWidthPx, scrollPx + viewWidthPx) / totalWidthPx) * durationMs;
  return { startMs, endMs };
}

// the zoom readout, "fit" or "120 px/s"
export function zoomLabel(pxPerS: number): string {
  return pxPerS > 0 ? `${Math.round(pxPerS)} px/s` : "fit";
}

// the largest value per column of the overview, from wavesurfer's decoded data
export function overviewPeaks(samples: Float32Array, columns: number): Float32Array {
  const out = new Float32Array(Math.max(0, columns));
  if (columns <= 0 || samples.length === 0) return out;
  const per = samples.length / columns;
  for (let c = 0; c < columns; c += 1) {
    const a = Math.floor(c * per);
    const b = Math.max(a + 1, Math.floor((c + 1) * per));
    let peak = 0;
    for (let i = a; i < b && i < samples.length; i += 1) peak = Math.max(peak, Math.abs(samples[i] ?? 0));
    out[c] = peak;
  }
  return out;
}
