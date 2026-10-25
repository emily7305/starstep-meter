import { afterEach, describe, expect, it, vi } from "vitest";
import { type ClockContext, ClockPlayer, START_LEAD_S } from "./clockPlayer";

class FakeSource {
  buffer: unknown = null;
  playbackRate = { value: 1 };
  started: [number, number] | null = null;
  stopped = false;
  onended: (() => void) | null = null;
  connect() {}
  disconnect() {}
  start(when: number, offset: number) {
    this.started = [when, offset];
  }
  stop() {
    this.stopped = true;
  }
}

class FakeContext {
  currentTime = 3;
  state: AudioContextState = "running";
  destination = {} as AudioNode;
  sources: FakeSource[] = [];
  resumed = 0;
  closed = false;
  createGain() {
    return { gain: { value: 1 }, connect() {}, disconnect() {} } as unknown as GainNode;
  }
  createBufferSource() {
    const source = new FakeSource();
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  }
  async decodeAudioData() {
    return { duration: 20 } as AudioBuffer;
  }
  async resume() {
    this.resumed += 1;
    this.state = "running";
  }
  async close() {
    this.closed = true;
  }
}

async function loaded(ctx = new FakeContext()): Promise<{ ctx: FakeContext; player: ClockPlayer }> {
  vi.stubGlobal("fetch", async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }));
  const player = new ClockPlayer(ctx as unknown as ClockContext);
  const ready = new Promise<void>((resolve) => player.addEventListener("canplay", resolve, { once: true }));
  player.src = "blob:song";
  await ready;
  return { ctx, player };
}

afterEach(() => vi.unstubAllGlobals());

describe("ClockPlayer", () => {
  it("loads the src into a buffer and says so like a media element", async () => {
    const { player } = await loaded();

    expect(player.duration).toBe(20);
    expect(player.currentTime).toBe(0);
    expect(player.paused).toBe(true);
  });

  it("starts the music a little ahead and maps song time onto that start exactly", async () => {
    const { ctx, player } = await loaded();
    player.currentTime = 7.5;

    await player.play();

    const source = ctx.sources[0];
    expect(source?.started).toEqual([3 + START_LEAD_S, 7.5]);
    // the click track schedules off this, it has to be the very time start() was given
    expect(player.contextTimeAt(7.5)).toBe(3 + START_LEAD_S);
    expect(player.contextTimeAt(8)).toBeCloseTo(3.55, 12);
  });

  it("holds the playhead through the start lead, then runs with the clock", async () => {
    const { ctx, player } = await loaded();
    player.currentTime = 2;
    await player.play();

    ctx.currentTime = 3.02;
    expect(player.currentTime).toBe(2);
    ctx.currentTime = 4.05;
    expect(player.currentTime).toBeCloseTo(3, 12);
  });

  it("pauses where it is and picks up from there", async () => {
    const { ctx, player } = await loaded();
    await player.play();
    ctx.currentTime = 4.05;

    player.pause();

    expect(player.paused).toBe(true);
    expect(player.currentTime).toBeCloseTo(1, 12);
    expect(ctx.sources[0]?.stopped).toBe(true);
    expect(player.contextTimeAt(1)).toBeNull();

    await player.play();
    expect(ctx.sources[1]?.started?.[1]).toBeCloseTo(1, 12);
  });

  it("restarts on a seek while playing, with a new epoch", async () => {
    const { ctx, player } = await loaded();
    await player.play();
    const epoch = player.epoch;
    ctx.currentTime = 5;

    player.currentTime = 12;

    expect(ctx.sources[0]?.stopped).toBe(true);
    expect(ctx.sources[1]?.started).toEqual([5 + START_LEAD_S, 12]);
    expect(player.epoch).toBeGreaterThan(epoch);
    expect(player.contextTimeAt(12)).toBe(5 + START_LEAD_S);
  });

  it("resumes a suspended context before it starts", async () => {
    const ctx = new FakeContext();
    ctx.state = "suspended";
    const { player } = await loaded(ctx);

    await player.play();

    expect(ctx.resumed).toBe(1);
    expect(ctx.sources).toHaveLength(1);
  });

  it("ends like a media element, timeupdate, pause, then ended", async () => {
    const { ctx, player } = await loaded();
    const events: string[] = [];
    for (const name of ["timeupdate", "pause", "ended"]) player.addEventListener(name, () => events.push(name));
    await player.play();

    ctx.sources[0]?.onended?.();

    expect(events).toEqual(["timeupdate", "pause", "ended"]);
    expect(player.ended).toBe(true);
    expect(player.currentTime).toBe(20);
  });

  it("says why when the audio can't be fetched", async () => {
    vi.stubGlobal("fetch", async () => ({ ok: false, status: 404 }));
    const player = new ClockPlayer(new FakeContext() as unknown as ClockContext);
    const failed = new Promise<void>((resolve) => player.addEventListener("error", resolve));

    player.src = "/api/jobs/x/audio";
    await failed;

    expect(player.error?.message).toBe("could not fetch the audio, http 404");
  });

  it("closes its context when it's done", async () => {
    const { ctx, player } = await loaded();

    player.destroy();

    expect(ctx.closed).toBe(true);
  });
});
