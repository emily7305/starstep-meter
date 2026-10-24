// tempo map edits, the ui side of PATCH /api/jobs/{id}/report
// anchor nudges are debounced like the old offset ones, everything else goes out at once,
// and only one patch is ever in flight so the server sees them in the order they were made

import type { TempoEditOp } from "./types/api";
import type { Edit, TempoSegment, TimingReport } from "./types/timingReport";

export const ANCHOR_STEP_MS = 1;
// how long an anchor has to sit still before it's saved, so holding an arrow key
// becomes one edit instead of one per millisecond
export const SAVE_DELAY_MS = 500;
// past this a bpm is a typo, the server refuses it too
export const MAX_BPM = 1000;

// same rounding as the backend, float steps of 1 ms pick up noise in the last digits
export function roundMs(value: number): number {
  return Math.round(value * 1000) / 1000;
}

export function nudged(anchorMs: number, steps: number): number {
  return roundMs(anchorMs + steps * ANCHOR_STEP_MS);
}

export function validBpm(bpm: number): boolean {
  return Number.isFinite(bpm) && bpm > 0 && bpm <= MAX_BPM;
}

// the field order the backend writes, so the optimistic entries come out in the same order
const SEGMENT_FIELDS = ["start_ms", "end_ms", "bpm", "anchor_ms", "confidence", "source"] as const;

// mirrors tempo_patch.py for the two value edits, so they show up before the patch comes back.
// split and merge refit on the server, there's nothing honest to show until it answers
export function withSegmentEdit(report: TimingReport, op: TempoEditOp, now: Date): TimingReport {
  if (op.op !== "set_anchor" && op.op !== "set_bpm") return report;
  const old = report.tempo_map[op.segment];
  if (old === undefined) return report;
  const changed: TempoSegment =
    op.op === "set_anchor"
      ? { ...old, anchor_ms: roundMs(op.anchor_ms), confidence: null, source: "manual" }
      : { ...old, bpm: op.bpm, confidence: null, source: "manual" };
  const timestamp = now.toISOString();
  const edits: Edit[] = SEGMENT_FIELDS.filter((key) => old[key] !== changed[key]).map((key) => ({
    field: `tempo_map/${op.segment}/${key}`,
    old: old[key],
    new: changed[key],
    timestamp,
  }));
  if (edits.length === 0) return report;
  const tempoMap = report.tempo_map.map((s, i) => (i === op.segment ? changed : s)) as TimingReport["tempo_map"];
  return { ...report, tempo_map: tempoMap, edits: [...report.edits, ...edits] };
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
  send: (op: TempoEditOp) => Promise<TimingReport>;
  onSaved: (report: TimingReport) => void;
  onState: (state: SaveState) => void;
  // the anchor the server already has, a nudge that ends up back there is never sent
  savedAnchor: (segment: number) => number | null;
  delayMs?: number;
  timers?: Timers;
}

export class EditSaver {
  private readonly options: SaverOptions;
  private readonly timers: Timers;
  private queue: TempoEditOp[] = [];
  private nudge: { segment: number; anchorMs: number } | null = null;
  private timer: unknown = null;
  private inFlight = false;
  private failed: TempoEditOp | null = null;
  private disposed = false;

  constructor(options: SaverOptions) {
    this.options = options;
    this.timers = options.timers ?? realTimers;
  }

  nudgeAnchor(segment: number, anchorMs: number): void {
    if (this.disposed) return;
    // a nudge on another segment closes the one before it and sends it
    if (this.nudge !== null && this.nudge.segment !== segment) {
      this.queueNudge();
      void this.pump();
    }
    this.nudge = { segment, anchorMs: roundMs(anchorMs) };
    this.failed = null;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.options.onState({ kind: "pending" });
    this.timer = this.timers.setTimeout(() => {
      this.timer = null;
      this.queueNudge();
      void this.pump();
    }, this.options.delayMs ?? SAVE_DELAY_MS);
  }

  submit(op: TempoEditOp): Promise<void> {
    if (this.disposed) return Promise.resolve();
    // a pending nudge was made first, so it goes first. split and merge move segment indices
    this.queueNudge();
    this.queue.push(op);
    this.failed = null;
    return this.pump();
  }

  // sends whatever is waiting now, and a failed edit once more
  retry(): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (this.failed !== null) {
      this.queue.unshift(this.failed);
      this.failed = null;
    }
    this.queueNudge();
    return this.pump();
  }

  get busy(): boolean {
    return this.inFlight || this.queue.length > 0 || this.nudge !== null;
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
  }

  private queueNudge(): void {
    if (this.timer !== null) this.timers.clearTimeout(this.timer);
    this.timer = null;
    const nudge = this.nudge;
    this.nudge = null;
    if (nudge === null) return;
    this.queue.push({ op: "set_anchor", segment: nudge.segment, anchor_ms: nudge.anchorMs });
  }

  private async pump(): Promise<void> {
    if (this.inFlight || this.disposed) return;
    while (this.queue.length > 0 && !this.disposed) {
      const op = this.queue.shift() as TempoEditOp;
      if (op.op === "set_anchor" && this.options.savedAnchor(op.segment) === op.anchor_ms) continue;
      this.inFlight = true;
      this.options.onState({ kind: "saving" });
      try {
        const report = await this.options.send(op);
        if (this.disposed) return;
        this.options.onSaved(report);
      } catch (err) {
        if (this.disposed) return;
        // edits after the failed one were made on top of it, they'd land on the wrong map
        this.failed = op;
        this.queue = [];
        this.options.onState({ kind: "failed", message: err instanceof Error ? err.message : "save failed" });
        return;
      } finally {
        this.inFlight = false;
      }
    }
    if (!this.disposed && this.nudge === null) this.options.onState({ kind: "saved" });
  }
}
