"""Decode: anything ffmpeg reads -> mono float32 wav at the native sample rate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.analysis.ffmpeg_tools import last_error_line, require_tool, run_tool


class DecodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DecodedAudio:
    path: Path
    sample_rate: int
    num_samples: int
    duration_ms: float


def decode_to_wav(src: Path, dst: Path) -> DecodedAudio:
    ffmpeg = require_tool("ffmpeg")
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
    )


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        # decode already downmixes, this is only for wavs passed in directly
        samples = samples.mean(axis=1, dtype=np.float32)
    return samples, int(sample_rate)
