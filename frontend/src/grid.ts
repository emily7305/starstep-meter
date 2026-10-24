// beat grid maths, kept free of dom and wavesurfer so it can be tested on its own
// times are ms on the decoded timeline, same as the report

export interface GridParams {
  // first downbeat, index 0
  offsetMs: number;
  bpm: number;
  beatsPerBar: number;
}

export interface GridLine {
  timeMs: number;
  // beats from the first downbeat, negative for pickups
  index: number;
  bar: number;
  isBar: boolean;
}

// what part of the waveform is on screen, in css px
export interface View {
  durationMs: number;
  // full width of the waveform at the current zoom
  totalWidthPx: number;
  scrollLeftPx: number;
  viewWidthPx: number;
}

export interface PlacedLine extends GridLine {
  // relative to the left edge of the view
  x: number;
}

export function periodMs(bpm: number): number {
  return 60000 / bpm;
}

export function timeToX(timeMs: number, durationMs: number, totalWidthPx: number): number {
  if (durationMs <= 0) return 0;
  return (timeMs / durationMs) * totalWidthPx;
}

export function xToTime(x: number, durationMs: number, totalWidthPx: number): number {
  if (totalWidthPx <= 0) return 0;
  return (x / totalWidthPx) * durationMs;
}

function floorDiv(a: number, b: number): number {
  return Math.floor(a / b);
}

function lineAt(params: GridParams, index: number): GridLine {
  const bar = floorDiv(index, params.beatsPerBar);
  return {
    timeMs: params.offsetMs + index * periodMs(params.bpm),
    index,
    bar,
    // js % keeps the sign, so -4 % 4 is -0 and -1 % 4 is -1, compare against the bar start instead
    isBar: index === bar * params.beatsPerBar,
  };
}

export function gridLines(params: GridParams, startMs: number, endMs: number): GridLine[] {
  if (!(params.bpm > 0) || params.beatsPerBar < 1 || endMs < startMs) return [];
  const period = periodMs(params.bpm);
  // || 0 because ceil of anything in (-1, 0) is -0, and the first downbeat should be index 0
  const first = Math.ceil((startMs - params.offsetMs) / period) || 0;
  const last = Math.floor((endMs - params.offsetMs) / period);
  const lines: GridLine[] = [];
  for (let index = first; index <= last; index += 1) lines.push(lineAt(params, index));
  return lines;
}

export function visibleLines(params: GridParams, view: View): PlacedLine[] {
  const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
  const startMs = Math.max(0, xToTime(scrollLeftPx, durationMs, totalWidthPx));
  const endMs = Math.min(durationMs, xToTime(scrollLeftPx + viewWidthPx, durationMs, totalWidthPx));
  return gridLines(params, startMs, endMs).map((line) => ({
    ...line,
    x: timeToX(line.timeMs, durationMs, totalWidthPx) - scrollLeftPx,
  }));
}

// px between two beats at this zoom, the plugin uses it to thin out lines that would blur together
export function beatSpacingPx(params: GridParams, view: View): number {
  return timeToX(periodMs(params.bpm), view.durationMs, view.totalWidthPx);
}

// line centre on a device pixel, so a 1 px line doesn't smear over two
export function crispX(x: number, devicePixelRatio: number, lineWidthDevicePx: number): number {
  const device = Math.round(x * devicePixelRatio);
  const half = lineWidthDevicePx % 2 === 1 ? 0.5 : 0;
  return (device + half) / devicePixelRatio;
}

export function nearestBeatMs(params: GridParams, timeMs: number): number {
  const period = periodMs(params.bpm);
  const index = Math.round((timeMs - params.offsetMs) / period);
  return params.offsetMs + index * period;
}
