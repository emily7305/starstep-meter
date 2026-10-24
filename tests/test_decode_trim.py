import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy import signal

from backend.analysis.decode import DecodeError, decode_to_wav, load_mono
from backend.analysis.trim import find_trim
from tests.synth import ClickTrackSpec, cached_click_wav

TRIM_TOLERANCE_MS = 10.0
# mp3 pre-echo pulls the start a little early, measured values are in docs/decisions.md
MP3_TRIM_TOLERANCE_MS = 15.0

BEATS = 16

CODECS = {
    "flac": ("flac", ["-c:a", "flac"]),
    "mp3": ("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
}

RATES = pytest.mark.parametrize("sample_rate", [44100, 48000], ids=["44k", "48k"])


def _encode(src: Path, dst: Path, codec_args: list[str]) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *codec_args, str(dst)],
        check=True,
    )
    return dst


def _roundtrip(tmp_path: Path, codec: str, sample_rate: int):
    ext, codec_args = CODECS[codec]
    wav, track = cached_click_wav(ClickTrackSpec(beats=BEATS, sample_rate=sample_rate))
    encoded = _encode(wav, tmp_path / f"song.{ext}", codec_args)
    decoded = decode_to_wav(encoded, tmp_path / "decoded.wav")
    samples, sr = load_mono(decoded.path)
    return decoded, samples, sr, track


def _lag_samples(decoded: np.ndarray, original: np.ndarray) -> int:
    # positive means the decoded audio starts later than the original
    corr = signal.correlate(decoded.astype(np.float64), original.astype(np.float64), mode="full", method="fft")
    lags = signal.correlation_lags(len(decoded), len(original), mode="full")
    return int(lags[np.argmax(corr)])


@pytest.mark.ffmpeg
@RATES
@pytest.mark.parametrize("codec", ["flac", "mp3"])
def test_decode_keeps_rate_and_is_mono(tmp_path, codec, sample_rate):
    decoded, samples, sr, _ = _roundtrip(tmp_path, codec, sample_rate)

    # no resampling, 48k stays 48k
    assert decoded.sample_rate == sample_rate
    assert sr == sample_rate
    assert sf.info(str(decoded.path)).channels == 1
    assert samples.ndim == 1
    assert decoded.num_samples == len(samples)
    assert decoded.duration_ms == pytest.approx(len(samples) / sr * 1000.0)


@pytest.mark.ffmpeg
@RATES
def test_flac_trim(tmp_path, sample_rate):
    _, samples, sr, track = _roundtrip(tmp_path, "flac", sample_rate)

    trim = find_trim(samples, sr)

    start_err = trim.start_ms - track.content_start_ms
    end_err = trim.end_ms - track.content_end_ms
    print(f"\nflac {sample_rate} hz: start err {start_err:+.3f} ms, end err {end_err:+.3f} ms")
    assert abs(start_err) <= TRIM_TOLERANCE_MS
    assert abs(end_err) <= TRIM_TOLERANCE_MS
    # lossless, so the length should survive too
    assert len(samples) == len(track.samples)


@pytest.mark.ffmpeg
@RATES
def test_mp3_trim_and_no_encoder_delay(tmp_path, sample_rate):
    _, samples, sr, track = _roundtrip(tmp_path, "mp3", sample_rate)

    trim = find_trim(samples, sr)
    lag = _lag_samples(samples, track.samples)

    start_err = trim.start_ms - track.content_start_ms
    end_err = trim.end_ms - track.content_end_ms
    print(
        f"\nmp3 {sample_rate} hz: start err {start_err:+.3f} ms, end err {end_err:+.3f} ms, "
        f"lag {lag:+d} samples ({lag / sr * 1000.0:+.3f} ms), length diff {len(samples) - len(track.samples):+d} samples"
    )
    assert abs(start_err) <= MP3_TRIM_TOLERANCE_MS
    assert abs(end_err) <= MP3_TRIM_TOLERANCE_MS
    # ffmpeg reads the lame header and drops the encoder delay, so the content
    # should sit where it was before encoding. an unskipped delay is ~1105 samples
    assert abs(lag) <= 1


@pytest.mark.ffmpeg
def test_garbage_file_cannot_be_decoded(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(bytes(range(256)) * 400)

    with pytest.raises(DecodeError):
        decode_to_wav(junk, tmp_path / "decoded.wav")
