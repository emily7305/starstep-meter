import { type PointerEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Palette } from "../theme";
import { overviewPeaks, type VisibleWindow } from "../timelineNav";

interface Props {
  // wavesurfer's decode of the whole song, enough for a strip this thin
  samples: Float32Array | null;
  durationMs: number;
  view: VisibleWindow | null;
  playheadMs: number;
  palette: Palette;
  onJump: (timeMs: number) => void;
}

const HEIGHT_PX = 30;

// the whole song in one thin strip, with the part the big timeline shows outlined. clicking or
// dragging in it moves that part there
export function Overview({ samples, durationMs, view, playheadMs, palette, onJump }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const dragging = useRef(false);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (wrap === null) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.floor(entry.contentRect.width));
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, []);

  const peaks = useMemo(() => (samples !== null && width > 0 ? overviewPeaks(samples, width) : null), [samples, width]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null || width <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(HEIGHT_PX * dpr);
    const ctx = canvas.getContext("2d");
    if (ctx === null) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, HEIGHT_PX);
    if (peaks !== null) {
      let loudest = 1e-6;
      for (const p of peaks) loudest = Math.max(loudest, p);
      const mid = HEIGHT_PX / 2;
      ctx.fillStyle = palette.inkFaint;
      peaks.forEach((p, x) => {
        const h = Math.max(1, (p / loudest) * (mid - 2));
        ctx.fillRect(x, mid - h, 1, 2 * h);
      });
    }
    if (durationMs <= 0) return;
    const toX = (ms: number) => (ms / durationMs) * width;
    if (view !== null && view.endMs - view.startMs < durationMs * 0.999) {
      const left = toX(view.startMs);
      const w = Math.max(3, toX(view.endMs) - left);
      ctx.fillStyle = palette.accent;
      ctx.globalAlpha = 0.1;
      ctx.fillRect(left, 0, w, HEIGHT_PX);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = palette.accent;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(left + 0.75, 0.75, w - 1.5, HEIGHT_PX - 1.5);
    }
    ctx.fillStyle = palette.accent;
    ctx.fillRect(Math.round(toX(playheadMs)) - 1, 0, 2, HEIGHT_PX);
  }, [peaks, width, durationMs, view, playheadMs, palette]);

  function timeAt(event: PointerEvent<HTMLDivElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0;
    return Math.min(1, Math.max(0, fraction)) * durationMs;
  }

  return (
    <div
      ref={wrapRef}
      className="overview"
      title="the whole song, the outlined part is what the timeline shows. click or drag to move it"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        onJump(timeAt(event));
      }}
      onPointerMove={(event) => {
        if (dragging.current) onJump(timeAt(event));
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
      onPointerCancel={() => {
        dragging.current = false;
      }}
    >
      <canvas
        ref={canvasRef}
        className="overview__canvas"
        style={{ width: `${width}px`, height: `${HEIGHT_PX}px` }}
        role="img"
        aria-label="whole song overview"
      />
    </div>
  );
}
