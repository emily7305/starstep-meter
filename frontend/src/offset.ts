// beat offset edits, the ui side of PATCH /api/jobs/{id}/report

import type { Edit, TimingReport } from "./types/timingReport";

export const OFFSET_STEP_MS = 1;
export const OFFSET_FIELD = "beat_offset_ms";
// how long the offset has to sit still before it's saved, so holding an arrow key
// becomes one edit instead of one per millisecond
export const SAVE_DELAY_MS = 500;

// same rounding as the backend, float steps of 1 ms pick up noise in the last digits
export function roundMs(value: number): number {
  return Math.round(value * 1000) / 1000;
}

export function nudged(offsetMs: number, steps: number): number {
  return roundMs(offsetMs + steps * OFFSET_STEP_MS);
}

// mirrors what the server appends, so the edit shows up before the patch comes back
export function withOffsetEdit(report: TimingReport, offsetMs: number, now: Date): TimingReport {
  const next = roundMs(offsetMs);
  const old = report.beat_offset_ms;
  if (old === next) return report;
  const edit: Edit = { field: OFFSET_FIELD, old, new: next, timestamp: now.toISOString() };
  return { ...report, beat_offset_ms: next, edits: [...report.edits, edit] };
}

export type SaveState =
  | { kind: "saved" }
  | { kind: "pending" }
  | { kind: "saving" }
  | { kind: "failed"; message: string };

export interface Timers {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

const realTimers: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface SaverOptions {
  // the value the server already has
  saved: number | null;
  send: (offsetMs: number) => Promise<TimingReport>;
  onSaved: (report: TimingReport) => void;
  onState: (state: SaveState) => void;
  delayMs?: number;
  timers?: Timers;
}

// one patch in flight at a time, always with the newest value. a value that ends up
// back where the server already is never gets sent
export class OffsetSaver {
  private saved: number | null;
  private pending: number | null = null;
  private timer: unknown = null;
  private inFlight = false;
  private disposed = false;
  private readonly options: SaverOptions;
  private readonly timers: Timers;

  constructor(options: SaverOptions) {
    this.options = options;
    this.saved = options.saved;
    this.timers = options.timers ?? realTimers;
  }

  push(offsetMs: number): void {
    if (this.disposed) return;
    this.pending = roundMs(offsetMs);
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.options.onState({ kind: "pending" });
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, this.options.delayMs ?? SAVE_DELAY_MS);
  }

  async flush(): Promise<void> {
    if (this.disposed || this.inFlight || this.pending === null) return;
    const value = this.pending;
    this.pending = null;
    if (value === this.saved) {
      this.options.onState({ kind: "saved" });
      return;
    }

    this.inFlight = true;
    this.options.onState({ kind: "saving" });
    try {
      const report = await this.options.send(value);
      if (this.disposed) return;
      this.saved = report.beat_offset_ms;
      this.options.onSaved(report);
      if (this.pending === null && this.timer === null) this.options.onState({ kind: "saved" });
    } catch (err) {
      if (this.disposed) return;
      // keep the value around so the next nudge or a retry still has it
      if (this.pending === null) this.pending = value;
      this.options.onState({ kind: "failed", message: err instanceof Error ? err.message : "save failed" });
      return;
    } finally {
      this.inFlight = false;
    }
    // a nudge landed while the patch was out and its timer already fired
    if (this.pending !== null && this.timer === null) await this.flush();
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }
}
