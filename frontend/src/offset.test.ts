import { describe, expect, it, vi } from "vitest";
import { nudged, OffsetSaver, roundMs, SAVE_DELAY_MS, withOffsetEdit } from "./offset";
import type { SaveState, Timers } from "./offset";
import type { Edit, TimingReport } from "./types/timingReport";

const NOW = new Date("2026-03-02T10:15:30.250Z");

function makeReport(overrides: Partial<TimingReport> = {}): TimingReport {
  return {
    schema_version: "1.1",
    source: {
      filename: "song.wav",
      sha256: "0".repeat(64),
      duration_ms: 22000,
      sample_rate: 44100,
      codec: "pcm_f32le",
      decoder_padding_samples: 0,
    },
    trim: { start_ms: 0, end_ms: 22000 },
    tempo_map: [{ start_ms: 0, bpm: 120, confidence: null, source: "auto" }],
    meter_map: [{ start_bar: 0, numerator: 4, denominator: 4, confidence: null, source: "auto" }],
    sections: [],
    beat_offset_ms: 137.5,
    edits: [],
    ...overrides,
  };
}

const bpmEdit: Edit = {
  field: "tempo_map/0/bpm",
  old: 119.8,
  new: 120,
  timestamp: "2026-03-01T08:00:00.000Z",
};
const labelEdit: Edit = {
  field: "sections/0/label",
  old: "intro",
  new: "verse",
  timestamp: "2026-03-01T08:05:00.000Z",
};

describe("roundMs", () => {
  it("keeps three decimals", () => {
    expect(roundMs(1.2344)).toBe(1.234);
    expect(roundMs(1.2346)).toBe(1.235);
    expect(roundMs(-1.2346)).toBe(-1.235);
    expect(roundMs(137.5)).toBe(137.5);
    expect(roundMs(2)).toBe(2);
  });

  it("drops float noise", () => {
    expect(roundMs(0.1 + 0.2)).toBe(0.3);
    expect(roundMs(128.00400000000002)).toBe(128.004);
  });

  it("is stable when applied twice", () => {
    const once = roundMs(137.5063);
    expect(roundMs(once)).toBe(once);
  });
});

describe("nudged", () => {
  it("steps by whole ms", () => {
    expect(nudged(137.506, 1)).toBe(138.506);
    expect(nudged(137.506, -3)).toBe(134.506);
    expect(nudged(137.5, 0)).toBe(137.5);
    expect(nudged(100, 10)).toBe(110);
  });

  it("doesn't carry the float noise of the step", () => {
    // 127.004 + 1 is 128.00400000000002 in floats
    expect(nudged(127.004, 1)).toBe(128.004);
  });
});

describe("withOffsetEdit", () => {
  it("appends one entry and sets the offset", () => {
    const before = makeReport({ beat_offset_ms: 137.5, edits: [bpmEdit, labelEdit] });

    const after = withOffsetEdit(before, 138.5, NOW);

    const entry = { field: "beat_offset_ms", old: 137.5, new: 138.5, timestamp: "2026-03-02T10:15:30.250Z" };
    expect(after.beat_offset_ms).toBe(138.5);
    expect(after.edits).toHaveLength(3);
    expect(after.edits[2]).toEqual(entry);
    // nothing else on the report moved
    expect(after).toEqual({ ...before, beat_offset_ms: 138.5, edits: [bpmEdit, labelEdit, entry] });
  });

  it("leaves the earlier edits as the same objects in the same order", () => {
    const before = makeReport({ edits: [bpmEdit, labelEdit] });

    const after = withOffsetEdit(before, 138.5, NOW);

    expect(after.edits[0]).toBe(bpmEdit);
    expect(after.edits[1]).toBe(labelEdit);
  });

  it("doesn't mutate the report it was given", () => {
    const before = makeReport({ edits: [bpmEdit, labelEdit] });
    const snapshot = structuredClone(before);

    const after = withOffsetEdit(before, 138.5, NOW);

    expect(before).toEqual(snapshot);
    expect(after).not.toBe(before);
    expect(after.edits).not.toBe(before.edits);
  });

  it("records a null old value when there was no offset yet", () => {
    const before = makeReport({ beat_offset_ms: null });

    const after = withOffsetEdit(before, 137.5, NOW);

    expect(after.beat_offset_ms).toBe(137.5);
    expect(after.edits).toEqual([
      { field: "beat_offset_ms", old: null, new: 137.5, timestamp: NOW.toISOString() },
    ]);
  });

  it("stores the rounded value", () => {
    const after = withOffsetEdit(makeReport({ beat_offset_ms: 137.506 }), 137.506 + 1, NOW);

    expect(after.beat_offset_ms).toBe(138.506);
    expect(after.edits[0]?.old).toBe(137.506);
    expect(after.edits[0]?.new).toBe(138.506);
  });

  it("rounds away float noise from the step", () => {
    // premise check, the plain sum really is off
    expect(127.004 + 1).not.toBe(128.004);

    const after = withOffsetEdit(makeReport({ beat_offset_ms: 127.004 }), 127.004 + 1, NOW);

    expect(after.beat_offset_ms).toBe(128.004);
    expect(after.edits[0]?.new).toBe(128.004);
  });

  it("returns the same report, with no new entry, for the same value", () => {
    const before = makeReport({ beat_offset_ms: 137.5, edits: [bpmEdit] });

    expect(withOffsetEdit(before, 137.5, NOW)).toBe(before);
    // rounds to the value it already has
    expect(withOffsetEdit(before, 137.5004, NOW)).toBe(before);
    expect(before.edits).toEqual([bpmEdit]);
  });

  it("chains old and new over two edits in a row", () => {
    const later = new Date("2026-03-02T10:15:31.000Z");

    const first = withOffsetEdit(makeReport({ beat_offset_ms: 137.5 }), 138.5, NOW);
    const second = withOffsetEdit(first, 140.5, later);

    expect(second.edits).toEqual([
      { field: "beat_offset_ms", old: 137.5, new: 138.5, timestamp: NOW.toISOString() },
      { field: "beat_offset_ms", old: 138.5, new: 140.5, timestamp: later.toISOString() },
    ]);
    expect(second.edits[0]).toBe(first.edits[0]);
    expect(first.edits).toHaveLength(1);
  });
});

// stands in for setTimeout, run() fires whatever is scheduled
function fakeTimers() {
  let nextHandle = 1;
  const scheduled = new Map<number, { fn: () => void; ms: number }>();
  const timers: Timers = {
    setTimeout: (fn, ms) => {
      const handle = nextHandle;
      nextHandle += 1;
      scheduled.set(handle, { fn, ms });
      return handle;
    },
    clearTimeout: (handle) => {
      scheduled.delete(handle as number);
    },
  };
  return {
    timers,
    count: () => scheduled.size,
    delays: () => [...scheduled.values()].map((timer) => timer.ms),
    run: () => {
      const due = [...scheduled.values()];
      scheduled.clear();
      for (const timer of due) timer.fn();
    },
  };
}

// every send stays pending until the test settles it, oldest first
function controlledSend() {
  const waiting: { resolve: (report: TimingReport) => void; reject: (reason: unknown) => void }[] = [];
  const send = vi.fn(
    (_offsetMs: number) =>
      new Promise<TimingReport>((resolve, reject) => {
        waiting.push({ resolve, reject });
      }),
  );
  function oldest() {
    const call = waiting.shift();
    if (call === undefined) throw new Error("no send is waiting");
    return call;
  }
  return {
    send,
    sent: () => send.mock.calls.map(([offsetMs]) => offsetMs),
    resolve: (report: TimingReport) => oldest().resolve(report),
    reject: (reason: unknown) => oldest().reject(reason),
  };
}

// lets the promise chain inside flush catch up
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function setup(saved: number | null = 137.5, delayMs?: number) {
  const clock = fakeTimers();
  const server = controlledSend();
  const states: SaveState[] = [];
  const reports: TimingReport[] = [];
  const saver = new OffsetSaver({
    saved,
    send: server.send,
    onSaved: (report) => reports.push(report),
    onState: (state) => states.push(state),
    timers: clock.timers,
    delayMs,
  });
  const kinds = () => states.map((state) => state.kind);
  return { saver, clock, server, states, reports, kinds };
}

describe("OffsetSaver", () => {
  it("sends once with the last value when three pushes land inside the delay", async () => {
    const { saver, clock, server, kinds } = setup(137.5);

    saver.push(138.5);
    saver.push(139.5);
    saver.push(140.5);

    // each push replaced the timer before it could fire
    expect(clock.count()).toBe(1);
    expect(server.sent()).toEqual([]);

    clock.run();
    expect(server.sent()).toEqual([140.5]);
    expect(kinds().at(-1)).toBe("saving");

    server.resolve(makeReport({ beat_offset_ms: 140.5 }));
    await settle();

    expect(server.sent()).toEqual([140.5]);
    expect(kinds()).toEqual(["pending", "pending", "pending", "saving", "saved"]);
  });

  it("sends nothing when the value is pushed back to the saved one", async () => {
    const { saver, clock, server, kinds } = setup(137.5);

    saver.push(138.5);
    saver.push(137.5);
    clock.run();
    await settle();

    expect(server.sent()).toEqual([]);
    expect(kinds()).toEqual(["pending", "pending", "saved"]);
  });

  it("rounds a push before comparing it with the saved value", async () => {
    // the plain sum is 128.00400000000002, which isn't what the server has
    const { saver, clock, server, kinds } = setup(128.004);

    saver.push(127.004 + 1);
    clock.run();
    await settle();

    expect(server.sent()).toEqual([]);
    expect(kinds().at(-1)).toBe("saved");
  });

  it("sends one more time with the newest value when a push lands mid-send", async () => {
    const { saver, clock, server, kinds } = setup(137.5);
    saver.push(138.5);
    clock.run();
    expect(server.sent()).toEqual([138.5]);

    saver.push(139.5);
    saver.push(140.5);
    // the delay runs out while the first send is still out
    clock.run();
    await settle();
    expect(server.sent()).toEqual([138.5]);

    server.resolve(makeReport({ beat_offset_ms: 138.5 }));
    await settle();
    expect(server.sent()).toEqual([138.5, 140.5]);

    server.resolve(makeReport({ beat_offset_ms: 140.5 }));
    await settle();
    expect(server.sent()).toEqual([138.5, 140.5]);
    expect(kinds().at(-1)).toBe("saved");
  });

  it("waits for the delay when a push lands mid-send and the first send ends first", async () => {
    const { saver, clock, server, kinds } = setup(137.5);
    saver.push(138.5);
    clock.run();

    saver.push(139.5);
    server.resolve(makeReport({ beat_offset_ms: 138.5 }));
    await settle();

    // 139.5 is still waiting on its timer, so it isn't saved yet
    expect(server.sent()).toEqual([138.5]);
    expect(kinds().at(-1)).toBe("pending");

    clock.run();
    expect(server.sent()).toEqual([138.5, 139.5]);

    server.resolve(makeReport({ beat_offset_ms: 139.5 }));
    await settle();
    expect(kinds().at(-1)).toBe("saved");
  });

  it("goes to failed with the error message when the send rejects", async () => {
    const { saver, clock, server, states, reports } = setup(137.5);

    saver.push(138.5);
    clock.run();
    server.reject(new Error("backend offline"));
    await settle();

    expect(states.at(-1)).toEqual({ kind: "failed", message: "backend offline" });
    expect(reports).toEqual([]);
  });

  it("falls back to a generic message when the rejection isn't an error", async () => {
    const { saver, clock, server, states } = setup(137.5);

    saver.push(138.5);
    clock.run();
    server.reject("nope");
    await settle();

    expect(states.at(-1)).toEqual({ kind: "failed", message: "save failed" });
  });

  it("retries the same value on flush after a failure", async () => {
    const { saver, clock, server, states, reports } = setup(137.5);
    saver.push(138.5);
    clock.run();
    server.reject(new Error("backend offline"));
    await settle();

    const retry = saver.flush();
    expect(server.sent()).toEqual([138.5, 138.5]);
    expect(states.at(-1)).toEqual({ kind: "saving" });

    const report = makeReport({ beat_offset_ms: 138.5 });
    server.resolve(report);
    await retry;

    expect(states.at(-1)).toEqual({ kind: "saved" });
    expect(reports).toEqual([report]);
  });

  it("hands the server's report to onSaved and treats its offset as the saved one", async () => {
    const { saver, clock, server, reports, kinds } = setup(137.5);
    saver.push(140.5);
    clock.run();

    // the server answers with a different offset than the one sent
    const fromServer = makeReport({ beat_offset_ms: 141 });
    server.resolve(fromServer);
    await settle();
    expect(reports).toHaveLength(1);
    expect(reports[0]).toBe(fromServer);

    saver.push(141);
    clock.run();
    await settle();
    expect(server.sent()).toEqual([140.5]);
    expect(kinds().at(-1)).toBe("saved");

    // 140.5 is no longer what the server has
    saver.push(140.5);
    clock.run();
    expect(server.sent()).toEqual([140.5, 140.5]);
  });

  it("cancels the pending timer on dispose and sends nothing after", async () => {
    const { saver, clock, server, kinds } = setup(137.5);
    saver.push(138.5);
    expect(clock.count()).toBe(1);

    saver.dispose();
    expect(clock.count()).toBe(0);

    clock.run();
    await saver.flush();
    saver.push(139.5);

    expect(clock.count()).toBe(0);
    expect(server.sent()).toEqual([]);
    expect(kinds()).toEqual(["pending"]);
  });

  it("ignores the answer of a send that is still out when disposed", async () => {
    const { saver, clock, server, reports, kinds } = setup(137.5);
    saver.push(138.5);
    clock.run();

    saver.dispose();
    server.resolve(makeReport({ beat_offset_ms: 138.5 }));
    await settle();

    expect(reports).toEqual([]);
    expect(kinds().at(-1)).toBe("saving");
  });

  it("waits SAVE_DELAY_MS by default", () => {
    const { saver, clock } = setup(137.5);

    saver.push(138.5);

    expect(clock.delays()).toEqual([SAVE_DELAY_MS]);
  });

  it("waits delayMs when one is given", () => {
    const { saver, clock } = setup(137.5, 120);

    saver.push(138.5);

    expect(clock.delays()).toEqual([120]);
  });
});
