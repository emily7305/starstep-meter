import hashlib
import io
import subprocess
from pathlib import Path

import pytest

from backend.analysis.ingest import (
    FileTooLargeError,
    UnsupportedFileError,
    check_extension,
    ingest_file,
    store_stream,
)
from tests.synth import ClickTrackSpec, cached_click_wav

MB = 1024 * 1024


def _payload(n: int) -> bytes:
    # a repeating ramp instead of zeros, so a dropped or doubled chunk changes the hash
    return (bytes(range(256)) * (n // 256 + 1))[:n]


def _encode(src: Path, dst: Path, *codec_args: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *codec_args, str(dst)],
        check=True,
    )
    return dst


# --- extension check ---


@pytest.mark.parametrize(
    "name",
    ["song.mp3", "song.wav", "song.flac", "song.ogg", "song.m4a", "LOUD.MP3", "Mixed.FlAc", "my.song.v2.WAV"],
)
def test_check_extension_accepts(name):
    assert check_extension(name) == Path(name).suffix.lower()


@pytest.mark.parametrize("name", ["notes.txt", "song", "song.mp3.zip"], ids=["txt", "no-extension", "wrapped"])
def test_check_extension_rejects(name):
    with pytest.raises(UnsupportedFileError, match="unsupported file type"):
        check_extension(name)


# --- store_stream ---


@pytest.mark.parametrize(
    "size",
    [0, 1, MB - 1, MB, MB + 1, 5 * MB // 2],
    ids=["empty", "1-byte", "just-under-chunk", "one-chunk", "just-over-chunk", "multi-chunk"],
)
def test_store_stream_hash_and_size(tmp_path, size):
    data = _payload(size)
    dest = tmp_path / "nested" / "original.wav"

    sha256, stored = store_stream(io.BytesIO(data), dest)

    assert sha256 == hashlib.sha256(data).hexdigest()
    assert stored == len(data)
    assert dest.read_bytes() == data


def test_store_stream_over_limit_leaves_nothing(tmp_path):
    # bigger than one read chunk, so the first chunk is already on disk when it trips
    data = _payload(5 * MB // 2)
    dest = tmp_path / "original.wav"

    with pytest.raises(FileTooLargeError):
        store_stream(io.BytesIO(data), dest, max_bytes=3 * MB // 2)

    assert not dest.exists()
    assert list(tmp_path.iterdir()) == []


def test_store_stream_exactly_at_limit_is_fine(tmp_path):
    # the check is size > max, so a file that is exactly the limit has to get through
    data = _payload(2048)
    dest = tmp_path / "original.wav"

    sha256, size = store_stream(io.BytesIO(data), dest, max_bytes=2048)

    assert size == 2048
    assert sha256 == hashlib.sha256(data).hexdigest()


def test_ingest_file_too_large_is_refused_before_anything_is_stored(tmp_path):
    src = tmp_path / "big.wav"
    src.write_bytes(_payload(2048))
    job_dir = tmp_path / "job"

    with pytest.raises(FileTooLargeError):
        ingest_file(src, job_dir, max_bytes=1024)

    assert not job_dir.exists() or list(job_dir.iterdir()) == []


# --- ingest_file, needs ffprobe ---


@pytest.mark.ffmpeg
def test_ingest_wav(tmp_path):
    wav, track = cached_click_wav(ClickTrackSpec(beats=8))
    job_dir = tmp_path / "job"

    result = ingest_file(wav, job_dir)

    assert result.sha256 == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert result.size_bytes == wav.stat().st_size
    assert result.filename == wav.name
    # the stored name stays boring on purpose, the upload name only lives in the report
    assert result.original_path == job_dir / "original.wav"
    assert result.original_path.read_bytes() == wav.read_bytes()
    assert result.probe.format_name == "wav"
    assert result.probe.sample_rate == 44100
    assert result.probe.channels == 1
    assert result.probe.duration_ms == pytest.approx(track.duration_ms, abs=1.0)


@pytest.mark.ffmpeg
def test_text_file_renamed_mp3_is_not_audio(tmp_path):
    # the extension passes, so only ffprobe can say no
    fake = tmp_path / "fake.mp3"
    fake.write_text("grocery list, not a song\n" * 200, encoding="utf-8")
    job_dir = tmp_path / "job"

    with pytest.raises(UnsupportedFileError, match=r"^not a readable audio file"):
        ingest_file(fake, job_dir)

    assert list(job_dir.glob("*")) == []


@pytest.mark.ffmpeg
def test_ingest_flac_is_probed_as_flac(tmp_path):
    wav, _ = cached_click_wav(ClickTrackSpec(beats=8))
    flac = _encode(wav, tmp_path / "song.flac", "-c:a", "flac")
    job_dir = tmp_path / "job"

    result = ingest_file(flac, job_dir)

    assert result.original_path == job_dir / "original.flac"
    assert result.sha256 == hashlib.sha256(flac.read_bytes()).hexdigest()
    assert result.probe.format_name == "flac"
    assert result.probe.codec_name == "flac"
    assert result.probe.sample_rate == 44100
    assert result.probe.channels == 1
