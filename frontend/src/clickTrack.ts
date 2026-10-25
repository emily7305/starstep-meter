// the click track: a click on every beat line of the tempo map and an accented one on every bar
// line, started at exact AudioContext times on the clock the music plays on (clockPlayer.ts).
// the interval only wakes the scheduler up to queue the next stretch, no click is timed by it,
// so timer jitter or a busy main thread can delay the queueing but never move a click

import { mapLines, type TempoGrid } from "./tempoMap";

export interface Click {
  timeMs: number;
  accent: boolean;
}

// how far ahead clicks are queued. the interval has to fire well inside this
export const LOOKAHEAD_S = 0.25;
export const WAKE_MS = 50;
export const CLICK_MS = 30;

// every line in [fromMs, toMs), mapLines takes both ends in
export function clicksBetween(grid: TempoGrid, fromMs: number, toMs: number): Click[] {
  if (toMs <= fromMs) return [];
  return mapLines(grid, fromMs, toMs)
    .filter((line) => line.timeMs >= fromMs && line.timeMs < toMs)
    .map((line) => ({ timeMs: line.timeMs, accent: line.isBar }));
}

// a short decaying sine. it starts at sample 0, so the onset is the time it's started at.
// pitch and level picked to cut through a full mix without masking the attack under it, tuned
// by ear on the test tracks only, revisit
export function clickSamples(sampleRate: number, accent: boolean): Float32Array<ArrayBuffer> {
  const freq = accent ? 1800 : 1200;
  const level = accent ? 0.9 : 0.5;
  // about -70 db by the cut at 30 ms, so the end of the buffer doesn't click on its own
  const decayS = 0.004;
  const out = new Float32Array(Math.round((sampleRate * CLICK_MS) / 1000));
  for (let i = 0; i < out.length; i += 1) {
    const t = i / sampleRate;
    out[i] = level * Math.sin(2 * Math.PI * freq * t) * Math.exp(-t / decayS);
  }
  return out;
}

// what the scheduler needs from the player and its context, a fake in the tests
export interface ClickClock {
  readonly context: {
    readonly currentTime: number;
    createBufferSource(): AudioBufferSourceNode;
  };
  readonly epoch: number;
  // the rendered position, not the playhead: the playhead trails it by the output latency, and
  // scheduling from that would eat the lookahead
  readonly songTime: number;
  contextTimeAt(songSeconds: number): number | null;
}

export interface ClickBuffers {
  plain: AudioBuffer;
  accent: AudioBuffer;
}

export interface WakeTimers {
  setInterval: (fn: () => void, ms: number) => unknown;
  clearInterval: (handle: unknown) => void;
}

const realTimers: WakeTimers = {
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (handle) => globalThis.clearInterval(handle as ReturnType<typeof setInterval>),
};

export class ClickScheduler {
  private readonly clock: ClickClock;
  private readonly output: AudioNode;
  private readonly buffers: ClickBuffers;
  private readonly timers: WakeTimers;
  private grid: TempoGrid | null = null;
  private enabled = false;
  private wake: unknown = null;
  private epoch = -1;
  // song time (s) up to which clicks are queued, null when nothing is
  private until: number | null = null;
  private queued = new Set<AudioBufferSourceNode>();

  constructor(clock: ClickClock, output: AudioNode, buffers: ClickBuffers, timers: WakeTimers = realTimers) {
    this.clock = clock;
    this.output = output;
    this.buffers = buffers;
    this.timers = timers;
  }

  setGrid(grid: TempoGrid | null): void {
    if (grid === this.grid) return;
    this.grid = grid;
    // an edit moves lines, the queued clicks would land on the old grid
    this.cancel();
    this.tick();
  }

  setEnabled(enabled: boolean): void {
    if (enabled === this.enabled) return;
    this.enabled = enabled;
    if (enabled) {
      this.wake = this.timers.setInterval(() => this.tick(), WAKE_MS);
      this.tick();
    } else {
      if (this.wake !== null) this.timers.clearInterval(this.wake);
      this.wake = null;
      this.cancel();
    }
  }

  get pending(): number {
    return this.queued.size;
  }

  dispose(): void {
    this.setEnabled(false);
  }

  tick(): void {
    if (!this.enabled || this.grid === null) return;
    if (this.clock.epoch !== this.epoch) {
      // played, paused or seeked, what's queued belongs to the old mapping
      this.cancel();
      this.epoch = this.clock.epoch;
    }
    const songNow = this.clock.songTime;
    if (this.clock.contextTimeAt(songNow) === null) return;
    const from = this.until ?? songNow;
    const to = songNow + LOOKAHEAD_S;
    if (to <= from) return;
    const now = this.clock.context.currentTime;
    for (const click of clicksBetween(this.grid, from * 1000, to * 1000)) {
      const when = this.clock.contextTimeAt(click.timeMs / 1000);
      // a click whose time is gone would sound late, better skipped
      if (when === null || when < now) continue;
      const node = this.clock.context.createBufferSource();
      node.buffer = click.accent ? this.buffers.accent : this.buffers.plain;
      node.connect(this.output);
      node.onended = () => {
        this.queued.delete(node);
        node.disconnect();
      };
      node.start(when);
      this.queued.add(node);
    }
    this.until = to;
  }

  private cancel(): void {
    for (const node of this.queued) {
      node.onended = null;
      try {
        node.stop();
      } catch {
        // never started or already done
      }
      node.disconnect();
    }
    this.queued.clear();
    this.until = null;
  }
}
