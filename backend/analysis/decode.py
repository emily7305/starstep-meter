"""Decode: anything ffmpeg reads -> mono float32 wav at the native sample rate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.analysis.ffmpeg_tools import last_error_line, require_tool, run_tool


class DecodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodecDelay:
    codec: str
    # what a decoder that ignores gapless info plays before ffmpeg's first sample, see docs/decisions.md
    decoder_padding_samples: int


@dataclass(frozen=True)
class DecodedAudio:
    path: Path
    sample_rate: int
    num_samples: int
    duration_ms: float
    codec: str
    decoder_padding_samples: int


def _padding_from_packet(packet: dict, time_base: Fraction, sample_rate: int) -> int:
    # ffmpeg drops leading samples either with skip side data or by starting at a negative pts,
    # some codecs do both with the same count (aac, opus), so take the larger, never the sum
    skip = 0
    for side in packet.get("side_data_list", []):
        if side.get("side_data_type") == "Skip Samples":
            skip = max(skip, int(side.get("skip_samples") or 0))
    pts = packet.get("pts")
    before_zero = 0
    if isinstance(pts, int) and pts < 0:
        before_zero = int(round(-pts * time_base * sample_rate))
    return max(skip, before_zero)


def probe_codec_delay(src: Path) -> CodecDelay:
    ffprobe = require_tool("ffprobe")
    # only the first couple of packets, the padding is all at the start
    proc = run_tool(
        [
            ffprobe, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,time_base:packet=pts:packet_side_data=side_data_type,skip_samples",
            "-read_intervals", "%+#2",
            "-of", "json",
            str(src),
        ],
        timeout_s=60.0,
    )
    if proc.returncode != 0:
        raise DecodeError(f"ffprobe could not read the stream ({last_error_line(proc.stderr, src)})")

    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    if not streams:
        raise DecodeError("file has no audio stream")
    stream = streams[0]
    codec = str(stream.get("codec_name") or "unknown")
    packets = info.get("packets", [])
    try:
        time_base = Fraction(str(stream.get("time_base")))
        sample_rate = int(stream.get("sample_rate") or 0)
    except (ValueError, ZeroDivisionError):
        time_base, sample_rate = Fraction(0), 0
    if not packets or sample_rate <= 0:
        return CodecDelay(codec=codec, decoder_padding_samples=0)
    return CodecDelay(codec=codec, decoder_padding_samples=_padding_from_packet(packets[0], time_base, sample_rate))


def decode_to_wav(src: Path, dst: Path) -> DecodedAudio:
    ffmpeg = require_tool("ffmpeg")
    delay = probe_codec_delay(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # no -ar on purpose, resampling here would smear timing before we even start
    # -vn skips embedded cover art, -map takes the first audio stream only
    proc = run_tool([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-map", "0:a:0", "-vn",
        "-ac", "1", "-c:a", "pcm_f32le",
        str(dst),
    ])
    if proc.returncode != 0 or not dst.exists():
        raise DecodeError(f"ffmpeg could not decode the file ({last_error_line(proc.stderr, src)})")

    # sample rate comes from the decoded file, not from ffprobe on the original
    info = sf.info(str(dst))
    if info.frames == 0:
        raise DecodeError("decoded audio is empty")
    return DecodedAudio(
        path=dst,
        sample_rate=int(info.samplerate),
        num_samples=int(info.frames),
        duration_ms=info.frames / info.samplerate * 1000.0,
        codec=delay.codec,
        decoder_padding_samples=delay.decoder_padding_samples,
    )


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        # decode already downmixes, this is only for wavs passed in directly
        samples = samples.mean(axis=1, dtype=np.float32)
    return samples, int(sample_rate)
