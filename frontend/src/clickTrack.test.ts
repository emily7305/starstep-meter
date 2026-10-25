import { describe, expect, it } from "vitest";
import {
  type ClickBuffers,
  type ClickClock,
  ClickScheduler,
  clickSamples,
  clicksBetween,
  LOOKAHEAD_S,
  type WakeTimers,
} from "./clickTrack";
import { tempoGrid } from "./tempoMap";
import type { MeterSegment, TempoSegment } from "./types/timingReport";

function seg(start: number, end: number, bpm: number, anchor: number): TempoSegment {
  return { start_ms: start, end_ms: end, bpm, anchor_ms: anchor, confidence: 1, source: "auto", notation_scale: 1, ratio_merged: [] };
}

function meter(start: number, end: number, numerator: number, denominator = 4): MeterSegment {
  return { start_ms: start, end_ms: end, numerator, denominator, confidence: 1, source: "auto" };
}

// 120 bpm from 1000 ms, 4/4, 20 s of audio
const GRID = tempoGrid([seg(500, 20000, 120, 1000)], [meter(500, 20000, 4)], 20000);

describe("clicksBetween", () => {
  it("clicks every beat and accents the bar lines", () => {
    expect(clicksBetween(GRID, 900, 3100)).toEqual([
      { timeMs: 1000, accent: true },
      { timeMs: 1500, accent: false },
      { timeMs: 2000, accent: false },
      { timeMs: 2500, accent: false },
      { timeMs: 3000, accent: true },
    ]);
  });

  it("takes the start in and leaves the end out, so windows don't overlap", () => {
    expect(clicksBetween(GRID, 1000, 2000).map((c) => c.timeMs)).toEqual([1000, 1500]);
    expect(clicksBetween(GRID, 2000, 3000).map((c) => c.timeMs)).toEqual([2000, 2500]);
  });

  it("clicks the beats before the first downbeat too", () => {
    // the grid runs back from the anchor to the start of the audio
    expect(clicksBetween(GRID, 0, 1000)).toEqual([
      { timeMs: 0, accent: false },
      { timeMs: 500, accent: false },
    ]);
  });

  it("accents a bar line between two beats", () => {
    // 7/8 from 1000 is 3.5 beats a bar, the second bar line sits half a beat in
    const grid = tempoGrid([seg(500, 20000, 120, 1000)], [meter(500, 20000, 7, 8)], 20000);

    expect(clicksBetween(grid, 2500, 3100)).toEqual([
      { timeMs: 2500, accent: false },
      { timeMs: 2750, accent: true },
      { timeMs: 3000, accent: false },
    ]);
  });

  it("follows a tempo change and restarts the bars there", () => {
    const grid = tempoGrid([seg(500, 5000, 120, 1000), seg(5000, 20000, 150, 5000)], [], 20000);

    expect(clicksBetween(grid, 4400, 5900)).toEqual([
      { timeMs: 4500, accent: false },
      { timeMs: 5000, accent: true },
      { timeMs: 5400, accent: false },
      { timeMs: 5800, accent: false },
    ]);
  });
});

describe("clickSamples", () => {
  it("starts on its first sample and dies away", () => {
    const plain = clickSamples(48000, false);
    const accent = clickSamples(48000, true);

    expect(plain.length).toBe(1440);
    expect(plain[0]).toBe(0);
    const peak = (xs: Float32Array, from: number, to: number) => Math.max(...xs.slice(from, to).map(Math.abs));
    // the loudest part is the first millisecond, the tail is near silent
    expect(peak(plain, 0, 48)).toBeGreaterThan(0.3);
    expect(peak(plain, 1300, 1440)).toBeLessThan(0.001);
    expect(peak(accent, 0, 48)).toBeGreaterThan(peak(plain, 0, 48));
  });
});

// a context clock the test moves by hand, and source nodes that only record what they were asked
class FakeNode {
  buffer: unknown = null;
  startedAt: number | null = null;
  stopped = false;
  onended: (() => void) | null = null;
  connect() {}
  disconnect() {}
  start(when: number) {
    this.startedAt = when;
  }
  stop() {
    this.stopped = true;
  }
}

class FakeClock implements ClickClock {
  nodes: FakeNode[] = [];
  epoch = 0;
  private songStart = 0;
  private contextStart: number | null = null;
  readonly context = {
    currentTime: 10,
    createBufferSource: () => {
      const node = new FakeNode();
      this.nodes.push(node);
      return node as unknown as AudioBufferSourceNode;
    },
  };

  // like ClockPlayer: song position songAt plays at contextAt
  play(songAt: number, contextAt: number) {
    this.songStart = songAt;
    this.contextStart = contextAt;
    this.epoch += 1;
  }

  pause() {
    this.contextStart = null;
    this.epoch += 1;
  }

  get songTime(): number {
    if (this.contextStart === null) return this.songStart;
    return this.songStart + Math.max(0, this.context.currentTime - this.contextStart);
  }

  contextTimeAt(song: number): number | null {
    return this.contextStart === null ? null : this.contextStart + (song - this.songStart);
  }

  started(): Array<[number, unknown]> {
    return this.nodes.filter((n) => !n.stopped).map((n) => [Number((n.startedAt ?? NaN).toFixed(6)), n.buffer]);
  }
}

const BUFFERS = { plain: "plain", accent: "accent" } as unknown as ClickBuffers;
const OUTPUT = {} as AudioNode;

function manualTimers(): WakeTimers & { running: boolean } {
  const timers = {
    running: false,
    setInterval: () => {
      timers.running = true;
      return 1;
    },
    clearInterval: () => {
      timers.running = false;
    },
  };
  return timers;
}

describe("ClickScheduler", () => {
  it("starts each click at the context time its beat plays at", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);
    // song 0.9 s plays at context 10.05, the start lead
    clock.play(0.9, 10.05);

    scheduler.setEnabled(true);

    // the window is 0.9 s to 0.9 + the lookahead, beat 1000 ms is 0.1 s after the start
    expect(LOOKAHEAD_S).toBe(0.25);
    expect(clock.started()).toEqual([[10.15, "accent"]]);
  });

  it("queues each beat once as the clock moves on", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);
    clock.play(0.9, 10.05);
    scheduler.setEnabled(true);

    for (let i = 0; i < 40; i += 1) {
      clock.context.currentTime += 0.05;
      scheduler.tick();
    }

    // 2 s of song after the start lead, beats from 1000 ms on every 500 ms
    const times = clock.started().map(([t]) => t);
    expect(times).toEqual([10.15, 10.65, 11.15, 11.65, 12.15]);
    expect(clock.started().map(([, b]) => b)).toEqual(["accent", "plain", "plain", "plain", "accent"]);
  });

  it("drops what was queued when the player seeks or pauses", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);
    clock.play(0.9, 10.05);
    scheduler.setEnabled(true);
    expect(clock.started()).toHaveLength(1);

    clock.pause();
    scheduler.tick();
    expect(clock.started()).toEqual([]);

    // played again from 2.95 s, the next beat is 3000 ms, 0.05 s after the music starts
    clock.context.currentTime = 20;
    clock.play(2.95, 20.05);
    scheduler.tick();
    expect(clock.started()).toEqual([[20.1, "accent"]]);
  });

  it("requeues on a new grid, so a nudged anchor is heard straight away", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);
    clock.play(0.9, 10.05);
    scheduler.setEnabled(true);

    scheduler.setGrid(tempoGrid([seg(500, 20000, 120, 1003)], [meter(500, 20000, 4)], 20000));

    expect(clock.started()).toEqual([[10.153, "accent"]]);
  });

  it("skips a click whose time has already gone", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);
    clock.play(0.9, 10.05);
    scheduler.setEnabled(true);
    expect(clock.started()).toEqual([[10.15, "accent"]]);

    // the main thread was busy for a second, the 1500 ms beat should have played at 10.65
    clock.context.currentTime = 11.1;
    scheduler.tick();

    // late is worse than missing, so 1500 is left out and 2000 still goes in on time
    expect(clock.started()).toEqual([
      [10.15, "accent"],
      [11.15, "plain"],
    ]);
  });

  it("stops everything and the wake up when it's switched off", () => {
    const clock = new FakeClock();
    const timers = manualTimers();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, timers);
    scheduler.setGrid(GRID);
    clock.play(0.9, 10.05);
    scheduler.setEnabled(true);
    expect(timers.running).toBe(true);

    scheduler.setEnabled(false);

    expect(timers.running).toBe(false);
    expect(clock.started()).toEqual([]);
    expect(scheduler.pending).toBe(0);
    // and nothing is queued while it's off
    scheduler.tick();
    expect(clock.started()).toEqual([]);
  });

  it("queues nothing while paused", () => {
    const clock = new FakeClock();
    const scheduler = new ClickScheduler(clock, OUTPUT, BUFFERS, manualTimers());
    scheduler.setGrid(GRID);

    scheduler.setEnabled(true);

    expect(clock.nodes).toEqual([]);
  });
});
