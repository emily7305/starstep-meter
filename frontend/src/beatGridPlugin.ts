// wavesurfer plugin that draws the tempo bands, the beat grid, the suggestion marks, the tempo and
// meter change labels and the low confidence shading over the waveform
// only the visible part gets drawn, a zoomed 4 minute song is far wider than any canvas can be

import BasePlugin, { type BasePluginEvents } from "wavesurfer.js/dist/base-plugin.js";
import { crispX, periodMs, timeToX, type View } from "./grid";
import { formatBpm } from "./format";
import { type Band, type TempoGrid, visibleMapLines } from "./tempoMap";

export interface BeatGridColors {
  beat: string;
  bar: string;
  label: string;
  labelBg: string;
  band: string;
  selected: string;
  bandLabel: string;
  offbeat: string;
  suggestion: string;
  change: string;
  lowConfidence: string;
}

// a stretch where the tracker followed the off-beat, shaded so it can be found and listened to
export interface OffbeatShade {
  startMs: number;
  endMs: number;
}

// an open notation suggestion, a thin bracket under the bar numbers
export interface SuggestionMark {
  startMs: number;
  endMs: number;
  selected: boolean;
}

// a stretch the analysis isn't sure of, see backend/analysis/confidence.py
export interface LowConfidenceShade {
  startMs: number;
  endMs: number;
}

// "m.21 · 130.00 bpm" at the line the change is on, from chartSetup.ts
export interface ChangeMark {
  timeMs: number;
  text: string;
  selected: boolean;
}

export interface TimelineMarks {
  offbeat: OffbeatShade[];
  suggestions: SuggestionMark[];
  lowConfidence: LowConfidenceShade[];
  changes: ChangeMark[];
}

export interface BeatGridOptions {
  grid: TempoGrid | null;
  bands: Band[];
  selected: number | null;
  marks: TimelineMarks;
  colors: BeatGridColors;
  labelFont: string;
}

// below this many px apart, lines turn into a smear, so thin them out
const MIN_BEAT_SPACING_PX = 5;
const MIN_LABEL_SPACING_PX = 36;
// the bpm labels sit along the bottom, the bar numbers along the top
const BAND_LABEL_H_PX = 16;
// hatching instead of a tint, the bands already use tints
const HATCH_SPACING_PX = 7;
// under the bar number labels, which end at 16 px
const MARK_Y_PX = 19;
const MARK_TICK_PX = 5;
// the change labels go under the suggestion marks
const CHANGE_Y_PX = 27;
const CHANGE_H_PX = 14;
const LOW_LABEL = "low confidence";

export class BeatGridPlugin extends BasePlugin<BasePluginEvents, BeatGridOptions> {
  private canvas: HTMLCanvasElement | null = null;
  private scrollLeft = 0;
  private frame = 0;

  static create(options: BeatGridOptions): BeatGridPlugin {
    return new BeatGridPlugin(options);
  }

  protected override onInit(): void {
    const ws = this.wavesurfer;
    if (!ws) return;

    const canvas = document.createElement("canvas");
    // above the waveform (z 2), under wavesurfer's cursor (z 5)
    canvas.style.cssText = "position:absolute;top:0;left:0;height:100%;pointer-events:none;z-index:3;";
    canvas.setAttribute("part", "beat-grid");
    ws.getWrapper().appendChild(canvas);
    this.canvas = canvas;

    const redraw = () => this.schedule();
    this.subscriptions.push(
      ws.on("scroll", (_start, _end, scrollLeft) => {
        this.scrollLeft = scrollLeft;
        redraw();
      }),
      ws.on("zoom", redraw),
      ws.on("redrawcomplete", redraw),
      ws.on("resize", redraw),
      ws.on("ready", redraw),
    );
    redraw();
  }

  setMap(grid: TempoGrid | null, bands: Band[], selected: number | null, marks: TimelineMarks): void {
    this.options.grid = grid;
    this.options.bands = bands;
    this.options.selected = selected;
    this.options.marks = marks;
    this.schedule();
  }

  override destroy(): void {
    cancelAnimationFrame(this.frame);
    this.canvas?.remove();
    this.canvas = null;
    super.destroy();
  }

  private schedule(): void {
    // scroll fires a lot while playing, one draw per frame is plenty
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(() => this.draw());
  }

  private drawBands(ctx: CanvasRenderingContext2D, view: View, heightPx: number): void {
    const { bands, selected, colors } = this.options;
    const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
    const toX = (ms: number) => timeToX(ms, durationMs, totalWidthPx) - scrollLeftPx;
    ctx.font = this.options.labelFont;
    ctx.textBaseline = "middle";
    for (const band of bands) {
      const left = toX(band.startMs);
      const right = toX(band.endMs);
      if (right < 0 || left > viewWidthPx) continue;
      const isSelected = band.index === selected;
      // every other band gets a faint tint so the boundaries read without a line of their own
      if (isSelected || band.index % 2 === 1) {
        ctx.fillStyle = isSelected ? colors.selected : colors.band;
        ctx.globalAlpha = isSelected ? 0.09 : 0.05;
        ctx.fillRect(left, 0, right - left, heightPx);
        ctx.globalAlpha = 1;
      }
      if (isSelected) {
        ctx.fillStyle = colors.selected;
        ctx.fillRect(left, heightPx - 2, right - left, 2);
      }

      const text = `${formatBpm(band.bpm)}${band.manual ? " · manual" : ""}`;
      const textW = ctx.measureText(text).width;
      // pinned to the left edge of the view while the band's start is scrolled off
      const x = Math.max(left, 0) + 4;
      if (x + textW + 6 > Math.min(right, viewWidthPx)) continue;
      const y = heightPx - BAND_LABEL_H_PX - 2;
      ctx.fillStyle = colors.labelBg;
      ctx.fillRect(x - 3, y, textW + 6, BAND_LABEL_H_PX - 2);
      ctx.fillStyle = isSelected ? colors.selected : colors.bandLabel;
      ctx.fillText(text, x, y + (BAND_LABEL_H_PX - 2) / 2);
    }
  }

  private drawOffbeat(ctx: CanvasRenderingContext2D, view: View, heightPx: number): void {
    const { colors } = this.options;
    const { offbeat } = this.options.marks;
    const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
    const bottom = heightPx - BAND_LABEL_H_PX;
    ctx.strokeStyle = colors.offbeat;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.22;
    for (const run of offbeat) {
      const left = timeToX(run.startMs, durationMs, totalWidthPx) - scrollLeftPx;
      const right = timeToX(run.endMs, durationMs, totalWidthPx) - scrollLeftPx;
      if (right < 0 || left > viewWidthPx) continue;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, 0, Math.max(right - left, 1), bottom);
      ctx.clip();
      ctx.beginPath();
      // diagonals from bottom left to top right, anchored to the run so they don't crawl on scroll
      for (let x = left - bottom; x < right; x += HATCH_SPACING_PX) {
        ctx.moveTo(x, bottom);
        ctx.lineTo(x + bottom, 0);
      }
      ctx.stroke();
      ctx.restore();
    }
    ctx.globalAlpha = 1;
  }

  private drawLowConfidence(ctx: CanvasRenderingContext2D, view: View, heightPx: number): void {
    const { colors } = this.options;
    const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
    const bottom = heightPx - BAND_LABEL_H_PX;
    ctx.fillStyle = colors.lowConfidence;
    for (const shade of this.options.marks.lowConfidence) {
      const left = timeToX(shade.startMs, durationMs, totalWidthPx) - scrollLeftPx;
      const right = timeToX(shade.endMs, durationMs, totalWidthPx) - scrollLeftPx;
      if (right < 0 || left > viewWidthPx) continue;
      // a darker wash plus a dotted edge with a label above the bpm labels. not a pink tint, that
      // means the selected segment
      ctx.fillStyle = colors.band;
      ctx.globalAlpha = 0.1;
      ctx.fillRect(left, 0, right - left, bottom);
      ctx.fillStyle = colors.lowConfidence;
      ctx.globalAlpha = 0.8;
      for (let x = Math.max(left, 0); x < Math.min(right, viewWidthPx); x += 4) ctx.fillRect(x, bottom - 3, 2, 2);
      ctx.globalAlpha = 1;
      ctx.font = this.options.labelFont;
      ctx.textBaseline = "middle";
      const x = Math.max(left, 0) + 4;
      if (x + ctx.measureText(LOW_LABEL).width + 4 < Math.min(right, viewWidthPx)) ctx.fillText(LOW_LABEL, x, bottom - 10);
    }
    ctx.globalAlpha = 1;
  }

  private drawChanges(ctx: CanvasRenderingContext2D, view: View): void {
    const { colors } = this.options;
    const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
    ctx.font = this.options.labelFont;
    ctx.textBaseline = "middle";
    let freeFrom = -Infinity;
    for (const change of this.options.marks.changes) {
      const x = timeToX(change.timeMs, durationMs, totalWidthPx) - scrollLeftPx;
      const w = ctx.measureText(change.text).width + 8;
      if (x + w < 0 || x > viewWidthPx) continue;
      // zoomed out, labels that would run into the one before are left out, the panel lists them all
      if (x < freeFrom && !change.selected) continue;
      ctx.fillStyle = colors.labelBg;
      ctx.fillRect(x, CHANGE_Y_PX, w, CHANGE_H_PX);
      ctx.fillStyle = change.selected ? colors.selected : colors.change;
      ctx.fillRect(x, CHANGE_Y_PX, 2, CHANGE_H_PX);
      ctx.fillText(change.text, x + 5, CHANGE_Y_PX + CHANGE_H_PX / 2);
      freeFrom = x + w + 4;
    }
  }

  private drawMarks(ctx: CanvasRenderingContext2D, view: View): void {
    const { colors } = this.options;
    const marks = this.options.marks.suggestions;
    const { durationMs, totalWidthPx, scrollLeftPx, viewWidthPx } = view;
    for (const mark of marks) {
      const left = timeToX(mark.startMs, durationMs, totalWidthPx) - scrollLeftPx;
      const right = timeToX(mark.endMs, durationMs, totalWidthPx) - scrollLeftPx;
      if (right < 0 || left > viewWidthPx) continue;
      // faint until picked from the list, then the accent, since it's where you are
      ctx.fillStyle = mark.selected ? colors.selected : colors.suggestion;
      ctx.globalAlpha = mark.selected ? 1 : 0.5;
      const h = mark.selected ? 2 : 1;
      ctx.fillRect(left, MARK_Y_PX, Math.max(right - left, 1), h);
      ctx.fillRect(left, MARK_Y_PX, 1, MARK_TICK_PX);
      ctx.fillRect(right - 1, MARK_Y_PX, 1, MARK_TICK_PX);
    }
    ctx.globalAlpha = 1;
  }

  private draw(): void {
    const ws = this.wavesurfer;
    const canvas = this.canvas;
    if (!ws || !canvas) return;

    const durationMs = ws.getDuration() * 1000;
    const viewWidthPx = ws.getWidth();
    const totalWidthPx = ws.getWrapper().clientWidth;
    const heightPx = canvas.parentElement?.clientHeight ?? 0;
    const dpr = window.devicePixelRatio || 1;

    // the canvas covers the view, not the whole wrapper, so it moves with the scroll
    canvas.style.left = `${this.scrollLeft}px`;
    canvas.style.width = `${viewWidthPx}px`;
    canvas.width = Math.max(1, Math.round(viewWidthPx * dpr));
    canvas.height = Math.max(1, Math.round(heightPx * dpr));

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const grid = this.options.grid;
    if (!grid || durationMs <= 0 || totalWidthPx <= 0) return;

    const view: View = { durationMs, totalWidthPx, scrollLeftPx: this.scrollLeft, viewWidthPx };
    ctx.scale(dpr, dpr);
    this.drawBands(ctx, view, heightPx);
    this.drawLowConfidence(ctx, view, heightPx);
    this.drawOffbeat(ctx, view, heightPx);
    this.drawMarks(ctx, view);

    // thinning goes by each segment's own period and shortest bar, a 240 bpm stretch thins out before a 120 one
    const steps = grid.segments.map((seg) => {
      const spacing = timeToX(periodMs(seg.segment.bpm), durationMs, totalWidthPx);
      const barSpacing = spacing * seg.barBeats;
      let barStep = 1;
      while (barSpacing * barStep < MIN_BEAT_SPACING_PX) barStep *= 2;
      let labelStep = barStep;
      while (barSpacing * labelStep < MIN_LABEL_SPACING_PX) labelStep *= 2;
      return { showBeats: spacing >= MIN_BEAT_SPACING_PX, barStep, labelStep };
    });

    const { colors } = this.options;
    for (const line of visibleMapLines(grid, view)) {
      const step = steps[line.segment];
      if (step === undefined) continue;
      if (!line.isBar && !step.showBeats) continue;
      if (line.isBar && line.bar % step.barStep !== 0) continue;
      const widthDevice = line.isBar ? 2 : 1;
      const x = crispX(line.x, dpr, widthDevice);
      ctx.fillStyle = line.isBar ? colors.bar : colors.beat;
      // beat lines share the waveform's colour, faded so the clicks under them still read
      ctx.globalAlpha = line.isBar ? 1 : 0.55;
      ctx.fillRect(x - widthDevice / 2 / dpr, 0, widthDevice / dpr, heightPx - BAND_LABEL_H_PX);
      ctx.globalAlpha = 1;

      if (line.isBar && line.bar % step.labelStep === 0) {
        const text = String(line.bar);
        ctx.font = this.options.labelFont;
        const w = ctx.measureText(text).width;
        ctx.fillStyle = colors.labelBg;
        ctx.fillRect(x + 2, 2, w + 6, 14);
        ctx.fillStyle = colors.label;
        ctx.textBaseline = "middle";
        ctx.fillText(text, x + 5, 9);
      }
    }
    this.drawChanges(ctx, view);
  }
}
