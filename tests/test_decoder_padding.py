import functools
import subprocess
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest
from scipy import signal

from backend.analysis.decode import CodecDelay, decode_to_wav, probe_codec_delay
from tests.synth import ClickTrackSpec, cached_click_wav

BEATS = 16


class Case(NamedTuple):
    id: str
    sample_rate: int
    ext: str
    # None = use the wav as it is
    codec_args: list[str] | None
    codec: str
    padding: int


CASES = [
    Case("mp3-lame-44k", 44100, "mp3", ["-c:a", "libmp3lame", "-b:a", "192k"], "mp3", 1105),
    Case("mp3-lame-48k", 48000, "mp3", ["-c:a", "libmp3lame", "-b:a", "192k"], "mp3", 1105),
    Case("mp3-no-lame-header", 44100, "mp3", ["-c:a", "libmp3lame", "-b:a", "192k", "-write_xing", "0"], "mp3", 0),
    Case("aac-m4a", 44100, "m4a", ["-c:a", "aac", "-b:a", "192k"], "aac", 1024),
    Case("vorbis", 44100, "ogg", ["-c:a", "libvorbis", "-q:a", "5"], "vorbis", 128),
    Case("opus", 44100, "ogg", ["-ar", "48000", "-c:a", "libopus", "-b:a", "128k"], "opus", 312),
    Case("flac", 44100, "flac", ["-c:a", "flac"], "flac", 0),
    Case("wav", 44100, "wav", None, "pcm_f32le", 0),
]

ALL_CASES = pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
NAIVE_CASES = pytest.mark.parametrize(
    "case", [c for c in CASES if c.id in ("mp3-lame-44k", "aac-m4a", "vorbis")], ids=lambda c: c.id
)


@functools.lru_cache(maxsize=1)
def _encoders() -> frozenset[str]:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True
    ).stdout
    # the legend sits above the dashed line and has rows that look like encoders
    rows = out.split("------", 1)[-1].splitlines()[1:]
    return frozenset(parts[1] for parts in (row.split() for row in rows) if len(parts) >= 2)


def _encode(src: Path, dst: Path, codec_args: list[str]) -> Path:
    encoder = codec_args[codec_args.index("-c:a") + 1]
    if encoder not in _encoders():
        pytest.skip(f"ffmpeg has no {encoder} encoder")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *codec_args, str(dst)],
        check=True,
    )
    return dst


def _make_source(tmp_path: Path, case: Case) -> Path:
    wav, _ = cached_click_wav(ClickTrackSpec(beats=BEATS, sample_rate=case.sample_rate))
    if case.codec_args is None:
        return wav
    return _encode(wav, tmp_path / f"song.{case.ext}", case.codec_args)


def _decode_f32(src: Path, naive: bool = False) -> np.ndarray:
    before_input = []
    if naive:
        before_input = ["-flags2", "+skip_manual"]
        if src.suffix == ".m4a":
            # mov demuxer option, mp3 and ogg reject it
            before_input += ["-ignore_editlist", "1"]
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", *before_input, "-i", str(src), "-ac", "1", "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _lag_samples(decoded: np.ndarray, original: np.ndarray) -> int:
    # positive means the decoded audio starts later than the original
    corr = signal.correlate(decoded.astype(np.float64), original.astype(np.float64), mode="full", method="fft")
    lags = signal.correlation_lags(len(decoded), len(original), mode="full")
    return int(lags[np.argmax(corr)])


@pytest.mark.ffmpeg
@ALL_CASES
def test_probe_reports_codec_and_padding(tmp_path, case):
    src = _make_source(tmp_path, case)

    assert probe_codec_delay(src) == CodecDelay(codec=case.codec, decoder_padding_samples=case.padding)


@pytest.mark.ffmpeg
@ALL_CASES
def test_decode_to_wav_carries_the_probe_result(tmp_path, case):
    src = _make_source(tmp_path, case)

    decoded = decode_to_wav(src, tmp_path / "decoded.wav")

    assert decoded.codec == case.codec
    assert decoded.decoder_padding_samples == case.padding


@pytest.mark.ffmpeg
@NAIVE_CASES
def test_padding_matches_naive_decoder_lag(tmp_path, case):
    src = _make_source(tmp_path, case)

    normal = _decode_f32(src)
    naive = _decode_f32(src, naive=True)
    lag = _lag_samples(naive, normal)

    # this is the ground truth, the probe has to agree with an actual decoder that ignores gapless info
    assert lag == case.padding
    assert probe_codec_delay(src).decoder_padding_samples == lag
