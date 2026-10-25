// reads the decoded wav (ffmpeg pcm_f32le, mono) at its own sample rate. wavesurfer decodes at 8 kHz
// and the audio context at the device rate, neither is the file's samples, the zoomed view needs those

export interface PcmAudio {
  sampleRate: number;
  samples: Float32Array;
}

const TAG_INT = 1;
const TAG_FLOAT = 3;
const TAG_EXTENSIBLE = 0xfffe;

function fourcc(view: DataView, at: number): string {
  return String.fromCharCode(
    view.getUint8(at),
    view.getUint8(at + 1),
    view.getUint8(at + 2),
    view.getUint8(at + 3),
  );
}

// the first channel as floats, null for anything this can't read. the samples are copied one by
// one: ffmpeg's data chunk starts at byte 106, so there's no aligned Float32Array view onto it, and
// a copy survives decodeAudioData detaching the buffer
export function parseWav(data: ArrayBuffer): PcmAudio | null {
  const view = new DataView(data);
  if (view.byteLength < 12 || fourcc(view, 0) !== "RIFF" || fourcc(view, 8) !== "WAVE") return null;

  let fmt: { tag: number; channels: number; sampleRate: number; blockAlign: number; bits: number } | null = null;
  let dataAt = -1;
  let dataSize = 0;
  let at = 12;
  while (at + 8 <= view.byteLength && (fmt === null || dataAt < 0)) {
    const id = fourcc(view, at);
    const size = view.getUint32(at + 4, true);
    const body = at + 8;
    if (id === "fmt ") {
      if (size < 16 || body + size > view.byteLength) return null;
      let tag = view.getUint16(body, true);
      // the real format is the first two bytes of the subformat guid, after cbSize, valid bits and the channel mask
      if (tag === TAG_EXTENSIBLE) {
        if (size < 40) return null;
        tag = view.getUint16(body + 24, true);
      }
      fmt = {
        tag,
        channels: view.getUint16(body + 2, true),
        sampleRate: view.getUint32(body + 4, true),
        blockAlign: view.getUint16(body + 12, true),
        bits: view.getUint16(body + 14, true),
      };
    } else if (id === "data") {
      // no recovering a data chunk that runs past the end, the tail would be silently missing
      if (body + size > view.byteLength) return null;
      dataAt = body;
      dataSize = size;
    }
    // chunks are padded to an even size
    at = body + size + (size % 2);
  }
  if (fmt === null || dataAt < 0) return null;

  const { tag, channels, sampleRate, blockAlign, bits } = fmt;
  const bytes = bits / 8;
  const known = (tag === TAG_INT && (bits === 16 || bits === 24 || bits === 32)) || (tag === TAG_FLOAT && (bits === 32 || bits === 64));
  if (!known || channels < 1 || sampleRate < 1 || blockAlign < channels * bytes) return null;

  const frames = Math.floor(dataSize / blockAlign);
  const samples = new Float32Array(frames);
  for (let i = 0; i < frames; i += 1) {
    const p = dataAt + i * blockAlign;
    if (tag === TAG_FLOAT) samples[i] = bits === 32 ? view.getFloat32(p, true) : view.getFloat64(p, true);
    else if (bits === 16) samples[i] = view.getInt16(p, true) / 32768;
    else if (bits === 24) samples[i] = (view.getInt16(p + 1, true) * 256 + view.getUint8(p)) / 8388608;
    else samples[i] = view.getInt32(p, true) / 2147483648;
  }
  return { sampleRate, samples };
}

// the fallback when the wav couldn't be read, at whatever rate the context decoded it to
export function pcmFromBuffer(buffer: AudioBuffer): PcmAudio {
  return { sampleRate: buffer.sampleRate, samples: buffer.getChannelData(0) };
}

// the sample indices [first, last) of the window, widened to whole samples and clamped to the data
export function sampleRange(pcm: PcmAudio, startMs: number, endMs: number): { first: number; last: number } {
  const n = pcm.samples.length;
  const first = Math.min(n, Math.max(0, Math.floor((startMs / 1000) * pcm.sampleRate)));
  const last = Math.min(n, Math.max(first, Math.ceil((endMs / 1000) * pcm.sampleRate)));
  return { first, last };
}
