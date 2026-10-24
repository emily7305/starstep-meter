"""The bpm range every tempo path searches, kept in one place.

The milestone 1 estimate (which the librosa fallback uses), madmom's
tracker and the tempo map all take a TempoRange, so changing the
default here changes it everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

# rhythm game songs go well past 240, a 270 bpm song came out at 135.51 with the old ceiling
# 320 is a guess at where charts stop, see docs/decisions.md for what it costs on slower songs
DEFAULT_MIN_BPM = 60.0
DEFAULT_MAX_BPM = 320.0


@dataclass(frozen=True)
class TempoRange:
    min_bpm: float = DEFAULT_MIN_BPM
    max_bpm: float = DEFAULT_MAX_BPM

    def __post_init__(self) -> None:
        if not 0.0 < self.min_bpm < self.max_bpm:
            raise ValueError(f"tempo range needs 0 < min_bpm < max_bpm, got {self.min_bpm:g}-{self.max_bpm:g}")

    def contains(self, bpm: float) -> bool:
        return self.min_bpm <= bpm <= self.max_bpm
