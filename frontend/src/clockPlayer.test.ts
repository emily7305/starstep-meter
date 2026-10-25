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

// the buffer the fake context decodes to, at its own rate like a real context
const DECODED = { duration: 20, sampleRate: 48000, getChannelData: () => new Float32Array([9, 9, 9]) } as unknown as AudioBuffer;

class FakeContext {
  currentTime = 3;
  outputLatency: number | undefined;
  baseLatency: number | undefined;
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
  async decodeAudioData(data: ArrayBuffer) {
    // a real decode detaches the buffer
    structuredClone(data, { transfer: [data] });
    return DECODED;
  }
  async resume() {
    this.resumed += 1;
    this.state = "running";
  }
  async close() {
    this.closed = true;
  }
}

// laid out like ffmpeg's pcm_f32le mono output: extensible fmt, fact, LIST, then the data
function ffmpegWav(rate: number, values: number[]): ArrayBuffer {
  const u16 = (n: number) => [n & 0xff, n >> 8];
  const u32 = (n: number) => [n & 0xff, (n >> 8) & 0xff, (n >> 16) & 0xff, (n >>> 24) & 0xff];
  const text = (s: string) => [...s].map((c) => c.charCodeAt(0));
  const chunk = (id: string, body: number[]) => [...text(id), ...u32(body.length), ...body, ...(body.length % 2 ? [0] : [])];
  const guid = [0x03, 0, 0, 0, 0, 0, 0x10, 0, 0x80, 0, 0, 0xaa, 0, 0x38, 0x9b, 0x71];
  const fmt = chunk("fmt ", [...u16(0xfffe), ...u16(1), ...u32(rate), ...u32(rate * 4), ...u16(4), ...u16(32), ...u16(22), ...u16(32), ...u32(4), ...guid]);
  const list = chunk("LIST", [...text("INFO"), ...text("ISFT"), ...u32(14), ...text("Lavf60.16.100"), 0]);
  const samples = new DataView(new ArrayBuffer(values.length * 4));
  values.forEach((v, i) => samples.setFloat32(i * 4, v, true));
  const data = chunk("data", [...new Uint8Array(samples.buffer)]);
  const body = [...text("WAVE"), ...fmt, ...chunk("fact", u32(values.length)), ...list, ...data];
  return new Uint8Array([...text("RIFF"), ...u32(body.length), ...body]).buffer;
}

async function loaded(
  ctx = new FakeContext(),
  body: () => ArrayBuffer = () => new ArrayBuffer(8),
): Promise<{ ctx: FakeContext; player: ClockPlayer }> {
  vi.stubGlobal("fetch", async () => ({ ok: true, arrayBuffer: async () => body() }));
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

  it("hands the zoomed view the wav's own samples, not the context's decode", async () => {
    const values = [0, 0.5, -0.25, 1, -1];
    const { player } = await loaded(new FakeContext(), () => ffmpegWav(44100, values));

    const pcm = player.samplesForView();

    expect(pcm?.sampleRate).toBe(44100);
    expect(Array.from(pcm?.samples ?? [])).toEqual(values);
    // the context decode is untouched, playback still runs on it
    expect(player.duration).toBe(20);
    expect(player.samplesForView()).toBe(pcm);
  });

  it("falls back to the context's decode when the response isn't a wav", async () => {
    const { player } = await loaded();

    const pcm = player.samplesForView();

    expect(pcm?.sampleRate).toBe(48000);
    expect(Array.from(pcm?.samples ?? [])).toEqual([9, 9, 9]);
    // the same object each time, the zoomed view is memoised on it
    expect(player.samplesForView()).toBe(pcm);
  });

  it("has no samples before the load and drops them on a new src", async () => {
    vi.stubGlobal("fetch", async () => ({ ok: true, arrayBuffer: async () => ffmpegWav(44100, [1]) }));
    const player = new ClockPlayer(new FakeContext() as unknown as ClockContext);
    expect(player.samplesForView()).toBeNull();
    const ready = new Promise<void>((resolve) => player.addEventListener("canplay", resolve, { once: true }));
    player.src = "blob:song";
    await ready;
    expect(player.samplesForView()).not.toBeNull();

    player.src = "";

    expect(player.samplesForView()).toBeNull();
  });
});

describe("ClockPlayer output latency", () => {
  async function playingWithLatency() {
    const ctx = new FakeContext();
    ctx.outputLatency = 0.15;
    ctx.baseLatency = 0.01;
    const { player } = await loaded(ctx);
    await player.play();
    return { ctx, player };
  }

  it("shows the time being heard, behind the rendered time by the latency", async () => {
    const { ctx, player } = await playingWithLatency();

    ctx.currentTime = 5.05;

    expect(player.songTime).toBeCloseTo(2, 12);
    expect(player.songTime - player.currentTime).toBeCloseTo(0.16, 12);
    expect(player.latencyInfo()).toEqual({ seconds: 0.16, output: true, base: true });
  });

  it("holds the playhead until the latency has passed, and never goes before the start", async () => {
    const { ctx, player } = await playingWithLatency();

    // 0.1 s after the start, less than the 0.16 s latency
    ctx.currentTime = 3.15;

    expect(player.currentTime).toBe(0);
    expect(player.songTime).toBeCloseTo(0.1, 12);
  });

  it("does not offset the audio or the clicks", async () => {
    const { ctx, player } = await playingWithLatency();

    expect(ctx.sources[0]?.started).toEqual([3 + START_LEAD_S, 0]);
    expect(player.contextTimeAt(0)).toBe(3 + START_LEAD_S);
    expect(player.contextTimeAt(1)).toBeCloseTo(4.05, 12);
  });

  it("pauses at the rendered position, where the audio stopped", async () => {
    const { ctx, player } = await playingWithLatency();
    ctx.currentTime = 5.05;

    player.pause();

    expect(player.currentTime).toBeCloseTo(2, 12);
    expect(player.songTime).toBeCloseTo(2, 12);
    await player.play();
    expect(ctx.sources[1]?.started?.[1]).toBeCloseTo(2, 12);
  });

  it("keeps the rendered position over a rate change", async () => {
    const { ctx, player } = await playingWithLatency();
    ctx.currentTime = 5.05;

    player.playbackRate = 0.5;

    expect(ctx.sources[1]?.started?.[1]).toBeCloseTo(2, 12);
  });

  it("reads the latency live, it can change while playing", async () => {
    const { ctx, player } = await playingWithLatency();
    ctx.currentTime = 5.05;

    ctx.outputLatency = 0.05;

    expect(player.songTime - player.currentTime).toBeCloseTo(0.06, 12);
  });

  it("ignores values that aren't usable", async () => {
    const ctx = new FakeContext();
    ctx.outputLatency = Number.NaN;
    ctx.baseLatency = -1;
    const { player } = await loaded(ctx);

    expect(player.latencyInfo()).toEqual({ seconds: 0, output: false, base: false });
  });

  it("is the rendered time when the browser reports neither", async () => {
    const { ctx, player } = await loaded();
    await player.play();
    ctx.currentTime = 5.05;

    expect(player.currentTime).toBe(player.songTime);
    expect(player.latencyInfo()).toEqual({ seconds: 0, output: false, base: false });
  });

  it("counts a reported zero as reported", async () => {
    const ctx = new FakeContext();
    ctx.outputLatency = 0;
    const { player } = await loaded(ctx);

    expect(player.latencyInfo()).toEqual({ seconds: 0, output: true, base: false });
  });
});
