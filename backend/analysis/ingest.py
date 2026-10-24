"""Ingest: check the upload is real audio, hash it, store it under the job dir."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from backend.analysis.ffmpeg_tools import last_error_line, require_tool, run_tool

ALLOWED_EXTENSIONS = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
# ffprobe reports m4a as "mov,mp4,m4a,3gp,3g2,mj2", so match on any comma-separated part
ALLOWED_FORMATS = frozenset({"mp3", "wav", "flac", "ogg", "m4a"})
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024


class IngestError(ValueError):
    pass


class UnsupportedFileError(IngestError):
    pass


class FileTooLargeError(IngestError):
    pass


@dataclass(frozen=True)
class ProbeResult:
    format_name: str
    codec_name: str
    sample_rate: int
    channels: int
    duration_ms: float | None


@dataclass(frozen=True)
class IngestResult:
    original_path: Path
    filename: str
    sha256: str
    size_bytes: int
    probe: ProbeResult


def check_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        shown = ext or "no extension"
        allowed = ", ".join(e.lstrip(".") for e in ALLOWED_EXTENSIONS)
        raise UnsupportedFileError(f"unsupported file type ({shown}), expected one of {allowed}")
    return ext


def store_stream(stream: BinaryIO, dest: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[str, int]:
    """Copy stream to dest while hashing, stop as soon as it goes over max_bytes."""
    digest = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as out:
            while chunk := stream.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise FileTooLargeError(f"file is larger than the {max_bytes // (1024 * 1024)} MB limit")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


def probe_audio(path: Path) -> ProbeResult:
    ffprobe = require_tool("ffprobe")
    proc = run_tool(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=format_name,duration:stream=codec_type,codec_name,sample_rate,channels",
            "-of", "json",
            str(path),
        ],
        timeout_s=60.0,
    )
    if proc.returncode != 0:
        raise UnsupportedFileError(f"not a readable audio file ({last_error_line(proc.stderr, path)})")

    info = json.loads(proc.stdout or "{}")
    fmt = info.get("format", {})
    format_name = str(fmt.get("format_name", ""))
    if not ALLOWED_FORMATS & set(format_name.split(",")):
        raise UnsupportedFileError(f"unsupported container ({format_name or 'unknown'})")

    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise UnsupportedFileError("file has no audio stream")
    stream = audio[0]

    # duration is missing for some raw streams, decode reads the real length anyway
    try:
        duration_ms: float | None = float(fmt["duration"]) * 1000.0
    except (KeyError, TypeError, ValueError):
        duration_ms = None

    return ProbeResult(
        format_name=format_name,
        codec_name=str(stream.get("codec_name", "")),
        sample_rate=int(stream.get("sample_rate") or 0),
        channels=int(stream.get("channels") or 0),
        duration_ms=duration_ms,
    )


def ingest_stream(
    stream: BinaryIO,
    filename: str,
    job_dir: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> IngestResult:
    ext = check_extension(filename)
    # keep the stored name boring, the real name only goes in the report
    dest = job_dir / f"original{ext}"
    sha256, size = store_stream(stream, dest, max_bytes)
    try:
        probe = probe_audio(dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return IngestResult(original_path=dest, filename=filename, sha256=sha256, size_bytes=size, probe=probe)


def ingest_file(src: Path, job_dir: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> IngestResult:
    check_extension(src.name)
    if src.stat().st_size > max_bytes:
        raise FileTooLargeError(f"file is larger than the {max_bytes // (1024 * 1024)} MB limit")
    with src.open("rb") as f:
        return ingest_stream(f, src.name, job_dir, max_bytes)
