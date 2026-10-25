import { describe, expect, it, vi } from "vitest";
import {
  EditSaver,
  MAX_BPM,
  nudged,
  roundMs,
  SAVE_DELAY_MS,
  validBpm,
  withSegmentEdit,
  type SaveState,
  type Timers,
} from "./tempoEdits";
import type { TempoEditOp } from "./types/api";
import type { Edit, TempoSegment, TimingReport } from "./types/timingReport";

const NOW = new Date("2026-03-02T10:15:30.250Z");

function seg(start: number, end: number, bpm: number, anchor: number, confidence: number | null = 1): TempoSegment {
  return {
    start_ms: start,
    end_ms: end,
    bpm,
    anchor_ms: anchor,
    confidence,
    source: confidence === null ? "manual" : "auto",
    ratio_merged: [],
  };
}

function makeReport(edits: Edit[] = []): TimingReport {
  return {
    schema_version: "2.4",
    source: {
      filename: "song.wav",
      sha256: "0".repeat(64),
      duration_ms: 40000,
      sample_rate: 44100,
      codec: "pcm_f32le",
      decoder_padding_samples: 0,
    },
    trim: { start_ms: 1000, end_ms: 38000 },
    tempo_map: [seg(1000, 17000, 120, 1000), seg(17000, 38000, 150, 17000)],
    meter_map: [],
    sections: [],
    offbeat_runs: [],
    notation_suggestions: [],
    confidence_spans: [],
    cross_check: null,
    edits,
  };
}

describe("roundMs and nudged", () => {
  it("keep three decimals and drop float noise", () => {
    expect(roundMs(0.1 + 0.2)).toBe(0.3);
    expect(roundMs(1.2346)).toBe(1.235);
    expect(nudged(127.004, 1)).toBe(128.004);
    expect(nudged(137.506, -3)).toBe(134.506);
  });
});

describe("validBpm", () => {
  it("takes 0 < bpm <= the max", () => {
    expect(validBpm(271.02)).toBe(true);
    // the 60-320 range is for detection, a hand-set bpm goes up to MAX_BPM
    expect(validBpm(440)).toBe(true);
    expect(validBpm(440 * 2)).toBe(true);
    expect(validBpm(MAX_BPM)).toBe(true);
    for (const bad of [0, -120, MAX_BPM + 1, Number.NaN, Number.POSITIVE_INFINITY]) expect(validBpm(bad)).toBe(false);
  });
});

describe("withSegmentEdit", () => {
  it("logs the anchor, the flip to manual and the dropped confidence as one entry, like the server", () => {
    const after = withSegmentEdit(makeReport(), { op: "set_anchor", segment: 1, anchor_ms: 17003 }, NOW);

    expect(after.tempo_map[1]).toEqual({ ...seg(17000, 38000, 150, 17003, null) });
    expect(after.edits).toEqual([
      {
        field: "tempo_map/1",
        old: { anchor_ms: 17000, confidence: 1, source: "auto" },
        new: { anchor_ms: 17003, confidence: null, source: "manual" },
        timestamp: "2026-03-02T10:15:30.250Z",
      },
    ]);
    expect(after.tempo_map[0]).toEqual(makeReport().tempo_map[0]);
  });

  it("logs only the value once a segment is already manual", () => {
    const report = { ...makeReport(), tempo_map: [seg(1000, 38000, 135.51, 1000, null)] as TimingReport["tempo_map"] };

    const after = withSegmentEdit(report, { op: "set_bpm", segment: 0, bpm: 271.02 }, NOW);

    expect(after.edits).toEqual([{ field: "tempo_map/0/bpm", old: 135.51, new: 271.02, timestamp: NOW.toISOString() }]);
  });

  it("leaves the report alone for a no-op, a bad index, or a split", () => {
    const report = makeReport();
    // the same bpm on an auto segment still marks it as set by hand
    const manual = withSegmentEdit(report, { op: "set_bpm", segment: 0, bpm: 120 }, NOW);
    expect(manual.edits.map((e) => [e.field, e.old, e.new])).toEqual([
      ["tempo_map/0", { confidence: 1, source: "auto" }, { confidence: null, source: "manual" }],
    ]);
    expect(withSegmentEdit(manual, { op: "set_bpm", segment: 0, bpm: 120 }, NOW)).toBe(manual);
    expect(withSegmentEdit(report, { op: "set_bpm", segment: 5, bpm: 120 }, NOW)).toBe(report);
    expect(withSegmentEdit(report, { op: "split", at_ms: 9000 }, NOW)).toBe(report);
  });
});

// fake timers, so the debounce runs when the test says so
function fakeTimers() {
  let next = 1;
  const pending = new Map<number, () => void>();
  const timers: Timers = {
    setTimeout: (fn) => {
      const id = next++;
      pending.set(id, fn);
      return id;
    },
    clearTimeout: (handle) => {
      pending.delete(handle as number);
    },
  };
  const fire = () => {
    const fns = [...pending.values()];
    pending.clear();
    for (const fn of fns) fn();
  };
  return { timers, fire, count: () => pending.size };
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setup(savedAnchor: (segment: number) => number | null = () => null) {
  const sent: TempoEditOp[] = [];
  const replies: ReturnType<typeof deferred<TimingReport>>[] = [];
  const states: SaveState["kind"][] = [];
  const saved: TimingReport[] = [];
  const { timers, fire, count } = fakeTimers();
  const saver = new EditSaver({
    send: (op) => {
      sent.push(op);
      const d = deferred<TimingReport>();
      replies.push(d);
      return d.promise;
    },
    onSaved: (r) => saved.push(r),
    onState: (s) => states.push(s.kind),
    savedAnchor,
    timers,
  });
  // lets the saver's awaits run
  const settle = () => new Promise((r) => setTimeout(r, 0));
  return { saver, sent, replies, states, saved, fire, count, settle };
}

describe("EditSaver", () => {
  it("turns a burst of nudges into one set_anchor with the newest value", async () => {
    const t = setup();
    t.saver.nudgeAnchor(1, 17001);
    t.saver.nudgeAnchor(1, 17002);
    t.saver.nudgeAnchor(1, 17003);
    expect(t.sent).toEqual([]);
    expect(t.count()).toBe(1);

    t.fire();
    expect(t.sent).toEqual([{ op: "set_anchor", segment: 1, anchor_ms: 17003 }]);
    t.replies[0]?.resolve(makeReport());
    await t.settle();
    expect(t.saved).toHaveLength(1);
    expect(t.states).toEqual(["pending", "pending", "pending", "saving", "saved"]);
  });

  it("uses the debounce delay", () => {
    const setTimeout = vi.fn(() => 1);
    const saver = new EditSaver({
      send: () => Promise.resolve(makeReport()),
      onSaved: () => {},
      onState: () => {},
      savedAnchor: () => null,
      timers: { setTimeout, clearTimeout: () => {} },
    });
    saver.nudgeAnchor(0, 1001);
    expect(setTimeout).toHaveBeenCalledWith(expect.any(Function), SAVE_DELAY_MS);
  });

  it("never sends a nudge that ended up back on the saved value", async () => {
    const t = setup(() => 17000);
    t.saver.nudgeAnchor(1, 17001);
    t.saver.nudgeAnchor(1, 17000);
    t.fire();
    await t.settle();

    expect(t.sent).toEqual([]);
    expect(t.states.at(-1)).toBe("saved");
  });

  it("sends a pending nudge before a split, in the order they were made", async () => {
    const t = setup();
    t.saver.nudgeAnchor(1, 17004);
    void t.saver.submit({ op: "split", at_ms: 25000 });

    expect(t.sent).toEqual([{ op: "set_anchor", segment: 1, anchor_ms: 17004 }]);
    expect(t.count()).toBe(0);
    t.replies[0]?.resolve(makeReport());
    await t.settle();
    expect(t.sent[1]).toEqual({ op: "split", at_ms: 25000 });
  });

  it("closes a nudge on one segment when another segment gets nudged", async () => {
    const t = setup();
    t.saver.nudgeAnchor(0, 1001);
    t.saver.nudgeAnchor(1, 17001);

    expect(t.sent).toEqual([{ op: "set_anchor", segment: 0, anchor_ms: 1001 }]);
    t.replies[0]?.resolve(makeReport());
    t.fire();
    await t.settle();
    expect(t.sent[1]).toEqual({ op: "set_anchor", segment: 1, anchor_ms: 17001 });
  });

  it("keeps one patch in flight", async () => {
    const t = setup();
    void t.saver.submit({ op: "set_bpm", segment: 0, bpm: 240 });
    void t.saver.submit({ op: "merge", segment: 0 });

    expect(t.sent).toHaveLength(1);
    t.replies[0]?.resolve(makeReport());
    await t.settle();
    expect(t.sent).toHaveLength(2);
    t.replies[1]?.resolve(makeReport());
    await t.settle();
    expect(t.saved).toHaveLength(2);
    expect(t.states.at(-1)).toBe("saved");
  });

  it("drops what was queued behind a failed edit and retries only that one", async () => {
    const t = setup();
    void t.saver.submit({ op: "set_bpm", segment: 0, bpm: 240 });
    void t.saver.submit({ op: "merge", segment: 0 });
    t.replies[0]?.reject(new Error("backend offline"));
    await t.settle();

    expect(t.states.at(-1)).toBe("failed");
    expect(t.sent).toHaveLength(1);
    expect(t.saver.busy).toBe(false);

    void t.saver.retry();
    expect(t.sent[1]).toEqual({ op: "set_bpm", segment: 0, bpm: 240 });
    t.replies[1]?.resolve(makeReport());
    await t.settle();
    expect(t.sent).toHaveLength(2);
    expect(t.states.at(-1)).toBe("saved");
  });

  it("does nothing after dispose", async () => {
    const t = setup();
    t.saver.nudgeAnchor(0, 1001);
    t.saver.dispose();
    t.fire();
    void t.saver.submit({ op: "split", at_ms: 5000 });
    await t.settle();

    expect(t.sent).toEqual([]);
    expect(t.count()).toBe(0);
  });
});
