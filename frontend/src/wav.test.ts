import { describe, expect, it } from "vitest";
import { type PcmAudio, parseWav, pcmFromBuffer, sampleRange } from "./wav";

const ascii = (s: string) => [...s].map((c) => c.charCodeAt(0));
const u16 = (n: number) => [n & 0xff, (n >> 8) & 0xff];
const u32 = (n: number) => [n & 0xff, (n >> 8) & 0xff, (n >> 16) & 0xff, (n >>> 24) & 0xff];

function chunk(id: string, body: number[]): number[] {
  return [...ascii(id), ...u32(body.length), ...body, ...(body.length % 2 ? [0] : [])];
}

function riff(chunks: number[][]): ArrayBuffer {
  const body = [...ascii("WAVE"), ...chunks.flat()];
  return new Uint8Array([...ascii("RIFF"), ...u32(body.length), ...body]).buffer;
}

function f32(values: number[]): number[] {
  const out = new DataView(new ArrayBuffer(values.length * 4));
  values.forEach((v, i) => out.setFloat32(i * 4, v, true));
  return [...new Uint8Array(out.buffer)];
}

function i16(values: number[]): number[] {
  return values.flatMap((v) => u16(v & 0xffff));
}

function plainFmt(tag: number, channels: number, rate: number, bits: number): number[] {
  const align = (channels * bits) / 8;
  return chunk("fmt ", [...u16(tag), ...u16(channels), ...u32(rate), ...u32(rate * align), ...u16(align), ...u16(bits)]);
}

// the layout of ffmpeg's pcm_f32le mono output, data at byte 106
function ffmpegWav(rate: number, values: number[]): ArrayBuffer {
  const fmt = chunk("fmt ", [
    ...u16(0xfffe),
    ...u16(1),
    ...u32(rate),
    ...u32(rate * 4),
    ...u16(4),
    ...u16(32),
    ...u16(22),
    ...u16(32),
    ...u32(4),
    // subformat guid, 03 00 is ieee float
    ...[0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10, 0x00, 0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71],
  ]);
  const fact = chunk("fact", u32(values.length));
  const list = chunk("LIST", [...ascii("INFO"), ...ascii("ISFT"), ...u32(14), ...ascii("Lavf60.16.100"), 0]);
  return riff([fmt, fact, list, chunk("data", f32(values))]);
}

describe("parseWav", () => {
  it("reads ffmpeg's extensible float layout, where the data chunk is not 4-byte aligned", () => {
    const values = [0, 0.5, -0.25, 1, -1, 0.125];
    const wav = ffmpegWav(44100, values);
    // the data chunk starts at 106 and its samples at 114, neither a multiple of 4
    expect(new DataView(wav).getUint32(106, true)).toBe(0x61746164);
    expect(wav.byteLength).toBe(114 + values.length * 4);

    const pcm = parseWav(wav);

    expect(pcm?.sampleRate).toBe(44100);
    expect(Array.from(pcm?.samples ?? [])).toEqual(values);
  });

  it("copies the samples, so detaching the buffer leaves them alone", () => {
    const wav = ffmpegWav(44100, [0.25, -0.5]);
    const pcm = parseWav(wav);

    structuredClone(wav, { transfer: [wav] });

    expect(wav.byteLength).toBe(0);
    expect(Array.from(pcm?.samples ?? [])).toEqual([0.25, -0.5]);
  });

  it("reads plain 16-bit pcm at 48000", () => {
    const pcm = parseWav(riff([plainFmt(1, 1, 48000, 16), chunk("data", i16([0, 16384, -16384, 32767, -32768]))]));

    expect(pcm?.sampleRate).toBe(48000);
    expect(Array.from(pcm?.samples ?? [])).toEqual([0, 0.5, -0.5, 32767 / 32768, -1]);
  });

  it("takes channel 0 of a stereo file", () => {
    const pcm = parseWav(riff([plainFmt(1, 2, 44100, 16), chunk("data", i16([8192, -1, -8192, 2, 16384, 3]))]));

    expect(pcm?.sampleRate).toBe(44100);
    expect(Array.from(pcm?.samples ?? [])).toEqual([0.25, -0.25, 0.5]);
  });

  it("reads 24-bit pcm and 64-bit float", () => {
    const i24 = [0x00, 0x00, 0x40, 0x00, 0x00, 0xc0, 0x01, 0x00, 0x00];
    expect(Array.from(parseWav(riff([plainFmt(1, 1, 44100, 24), chunk("data", i24)]))?.samples ?? [])).toEqual([
      0.5,
      -0.5,
      1 / 8388608,
    ]);

    const f64 = new DataView(new ArrayBuffer(16));
    f64.setFloat64(0, 0.1, true);
    f64.setFloat64(8, -0.75, true);
    const pcm = parseWav(riff([plainFmt(3, 1, 44100, 64), chunk("data", [...new Uint8Array(f64.buffer)])]));
    expect(Array.from(pcm?.samples ?? [])).toEqual([Math.fround(0.1), -0.75]);
  });

  it("skips a chunk with an odd size and its pad byte", () => {
    const pcm = parseWav(riff([plainFmt(1, 1, 44100, 16), chunk("junk", [1, 2, 3]), chunk("data", i16([100]))]));

    expect(Array.from(pcm?.samples ?? [])).toEqual([100 / 32768]);
  });

  it("gives null for what it can't read", () => {
    expect(parseWav(new ArrayBuffer(0))).toBeNull();
    expect(parseWav(new TextEncoder().encode("this is not a wav file at all").buffer as ArrayBuffer)).toBeNull();
    expect(parseWav(new Uint8Array([...ascii("RIFF"), ...u32(4), ...ascii("AVI ")]).buffer)).toBeNull();
    // 8-bit and a made up format tag
    expect(parseWav(riff([plainFmt(1, 1, 44100, 8), chunk("data", [1, 2])]))).toBeNull();
    expect(parseWav(riff([plainFmt(2, 1, 44100, 16), chunk("data", i16([1]))]))).toBeNull();
    // no fmt, no data
    expect(parseWav(riff([chunk("data", i16([1]))]))).toBeNull();
    expect(parseWav(riff([plainFmt(1, 1, 44100, 16)]))).toBeNull();
  });

  it("gives null for truncated files", () => {
    const wav = ffmpegWav(44100, [0.1, 0.2, 0.3, 0.4]);
    // cut inside the samples, inside the header, and inside the fmt chunk
    expect(parseWav(wav.slice(0, wav.byteLength - 3))).toBeNull();
    expect(parseWav(wav.slice(0, 60))).toBeNull();
    expect(parseWav(wav.slice(0, 20))).toBeNull();
  });
});

describe("pcmFromBuffer", () => {
  it("takes the first channel at the buffer's rate", () => {
    const first = new Float32Array([0.5]);
    const buffer = { sampleRate: 48000, getChannelData: (c: number) => (c === 0 ? first : new Float32Array(1)) };

    const pcm = pcmFromBuffer(buffer as unknown as AudioBuffer);

    expect(pcm.sampleRate).toBe(48000);
    expect(pcm.samples).toBe(first);
  });
});

describe("sampleRange", () => {
  const pcm = (n: number): PcmAudio => ({ sampleRate: 44100, samples: new Float32Array(n) });

  it("covers a 40 ms window around 1000 ms, widened to whole samples", () => {
    expect(sampleRange(pcm(10 * 44100), 980, 1020)).toEqual({
      first: Math.floor(0.98 * 44100),
      last: Math.ceil(1.02 * 44100),
    });
  });

  it("clamps to the data at both ends", () => {
    expect(sampleRange(pcm(44100), -20, 20)).toEqual({ first: 0, last: Math.ceil(0.02 * 44100) });
    expect(sampleRange(pcm(44100), 990, 1010)).toEqual({ first: Math.floor(0.99 * 44100), last: 44100 });
  });

  it("is empty when the window is outside the data", () => {
    expect(sampleRange(pcm(44100), 2000, 2040)).toEqual({ first: 44100, last: 44100 });
    expect(sampleRange(pcm(44100), -80, -40)).toEqual({ first: 0, last: 0 });
  });
});
