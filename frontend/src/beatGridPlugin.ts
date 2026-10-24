// wavesurfer plugin that draws the tempo bands and the beat grid over the waveform
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
}

export interface BeatGridOptions {
  grid: TempoGrid | null;
  bands: Band[];
  selected: number | null;
  colors: BeatGridColors;
  labelFont: string;
}

// below this many px apart, lines turn into a smear, so thin them out
const MIN_BEAT_SPACING_PX = 5;
const MIN_LABEL_SPACING_PX = 36;
// the bpm labels sit along the bottom, the bar numbers along the top
const BAND_LABEL_H_PX = 16;

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

  setMap(grid: TempoGrid | null, bands: Band[], selected: number | null): void {
    this.options.grid = grid;
    this.options.bands = bands;
    this.options.selected = selected;
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

    // thinning goes by each segment's own period, a 240 bpm stretch thins out before a 120 one
    const steps = grid.segments.map((seg) => {
      const spacing = timeToX(periodMs(seg.segment.bpm), durationMs, totalWidthPx);
      const barSpacing = spacing * grid.beatsPerBar;
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
  }
}
