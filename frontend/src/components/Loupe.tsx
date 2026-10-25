import { useEffect, useRef, useState } from "react";
import { crispX } from "../grid";
import { mapLines, type TempoGrid } from "../tempoMap";
import type { Palette } from "../theme";
import { type PcmAudio, sampleRange } from "../wav";

interface Props {
  audio: PcmAudio | null;
  grid: TempoGrid | null;
  // audio time at the centre, it stays put while the anchor moves so the line slides over the attack
  centerMs: number | null;
  spanMs: number;
  // snapped beat times from the beats file, drawn as ticks to compare against the grid
  trackedMs: number[];
  palette: Palette;
}

const HEIGHT_PX = 132;
const SCALE_H_PX = 16;

function draw(canvas: HTMLCanvasElement, widthPx: number, props: Props): void {
  const { audio, grid, centerMs, spanMs, trackedMs, palette } = props;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(widthPx * dpr));
  canvas.height = Math.round(HEIGHT_PX * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, widthPx, HEIGHT_PX);
  if (centerMs === null) return;

  const startMs = centerMs - spanMs / 2;
  const endMs = centerMs + spanMs / 2;
  const toX = (ms: number) => ((ms - startMs) / spanMs) * widthPx;
  const waveH = HEIGHT_PX - SCALE_H_PX;
  const mid = waveH / 2;

  if (audio !== null) {
    // the file's own samples at its own rate, times go through that rate
    const data = audio.samples;
    const rate = audio.sampleRate;
    const { first, last } = sampleRange(audio, startMs, endMs);
    // scale to the loudest sample in view, a quiet intro would be a flat line otherwise
    let peak = 1e-6;
    for (let i = first; i < last; i += 1) peak = Math.max(peak, Math.abs(data[i] ?? 0));

    ctx.fillStyle = palette.inkSoft;
    for (let x = 0; x < widthPx; x += 1) {
      const a = Math.floor(((startMs + (x / widthPx) * spanMs) / 1000) * rate);
      const b = Math.max(a + 1, Math.floor(((startMs + ((x + 1) / widthPx) * spanMs) / 1000) * rate));
      if (b <= 0 || a >= data.length) continue;
      let lo = 0;
      let hi = 0;
      for (let i = Math.max(0, a); i < Math.min(data.length, b); i += 1) {
        const v = data[i] ?? 0;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      const top = mid - (hi / peak) * mid * 0.92;
      const bottom = mid - (lo / peak) * mid * 0.92;
      ctx.fillRect(x, top, 1, Math.max(1 / dpr, bottom - top));
    }
  }

  // ms scale along the bottom, a tick per ms once there's room for it
  const pxPerMs = widthPx / spanMs;
  ctx.fillStyle = palette.line;
  ctx.fillRect(0, waveH, widthPx, 1);
  const tickEvery = pxPerMs >= 3 ? 1 : pxPerMs >= 0.6 ? 5 : 10;
  ctx.fillStyle = palette.inkFaint;
  for (let ms = Math.ceil(startMs / tickEvery) * tickEvery; ms <= endMs; ms += tickEvery) {
    const long = Math.round(ms) % 10 === 0;
    ctx.fillRect(crispX(toX(ms), dpr, 1) - 0.5 / dpr, waveH, 1 / dpr, long ? 7 : 3);
  }

  ctx.fillStyle = palette.ink;
  for (const t of trackedMs) {
    if (t < startMs || t > endMs) continue;
    const x = toX(t);
    ctx.beginPath();
    ctx.moveTo(x, waveH - 1);
    ctx.lineTo(x - 4, waveH - 8);
    ctx.lineTo(x + 4, waveH - 8);
    ctx.closePath();
    ctx.fill();
  }

  if (grid !== null) {
    for (const line of mapLines(grid, startMs, endMs)) {
      const widthDevice = line.isBar ? 2 : 1;
      const x = crispX(toX(line.timeMs), dpr, widthDevice);
      ctx.fillStyle = line.isBar ? palette.mint : palette.ink;
      ctx.fillRect(x - widthDevice / 2 / dpr, 0, widthDevice / dpr, waveH);
    }
  }
}

export function Loupe(props: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (wrap === null) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas !== null && width > 0) draw(canvas, width, props);
  });

  return (
    <div className="loupe" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className="loupe__canvas"
        style={{ width: `${width}px`, height: `${HEIGHT_PX}px` }}
        role="img"
        aria-label={`zoomed view, ${props.spanMs} ms wide`}
      />
    </div>
  );
}
