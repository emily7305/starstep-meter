"""Server settings, read from STARSTEP_* env vars."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from backend.analysis.snap import DEFAULT_WINDOW_MS
from backend.analysis.tempo_range import DEFAULT_MAX_BPM, DEFAULT_MIN_BPM, TempoRange
from backend.analysis.trim import DEFAULT_THRESHOLD_DB

# parents[0] is backend/api, so [2] lands on the repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

T = TypeVar("T")


def _read_env(name: str, cast: Callable[[str], T], default: T) -> T:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        # fail at startup with the var name in it, a bare int() error doesn't say which one
        raise ValueError(f"{name} must be a {cast.__name__}, got {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    data_dir: Path = REPO_ROOT / "data"
    max_upload_mb: int = 100
    trim_threshold_db: float = DEFAULT_THRESHOLD_DB
    snap_window_ms: float = DEFAULT_WINDOW_MS
    min_bpm: float = DEFAULT_MIN_BPM
    max_bpm: float = DEFAULT_MAX_BPM
    # one worker is plenty, analysis is cpu bound and it's just me using it
    workers: int = 1

    def __post_init__(self) -> None:
        if self.max_upload_mb < 1:
            raise ValueError("max_upload_mb must be at least 1")
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        if self.snap_window_ms <= 0:
            raise ValueError("snap_window_ms must be positive")
        # TempoRange checks the bounds and names them in its error
        TempoRange(self.min_bpm, self.max_bpm)

    @property
    def tempo_range(self) -> TempoRange:
        return TempoRange(self.min_bpm, self.max_bpm)

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            data_dir=_read_env("STARSTEP_DATA_DIR", lambda raw: Path(raw).expanduser(), defaults.data_dir),
            max_upload_mb=_read_env("STARSTEP_MAX_UPLOAD_MB", int, defaults.max_upload_mb),
            trim_threshold_db=_read_env("STARSTEP_TRIM_THRESHOLD_DB", float, defaults.trim_threshold_db),
            snap_window_ms=_read_env("STARSTEP_SNAP_WINDOW_MS", float, defaults.snap_window_ms),
            min_bpm=_read_env("STARSTEP_MIN_BPM", float, defaults.min_bpm),
            max_bpm=_read_env("STARSTEP_MAX_BPM", float, defaults.max_bpm),
            workers=_read_env("STARSTEP_WORKERS", int, defaults.workers),
        )
