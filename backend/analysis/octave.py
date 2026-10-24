"""Octave check: is the tracked tempo the beat, or half or double of it.

Both trackers can land an octave off. madmom's network hears 250-300 bpm
clicks as half time, and the m1 estimate that drives the librosa fallback
doubles anything with audible eighth notes now that the range goes to 320.
So after tracking, one rule for both: look at how strong the onsets are on
the tracked beats, between them, and on every other beat, and double or
halve once if they clearly say so. Where they don't, the tracker's choice
stands, see docs/decisions.md for where that still goes wrong.

It runs once per rough tempo segment, because madmom can follow a song at
the right tempo and then drop to half time for one section of it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from backend.analysis.beats import FALLBACK_BEATS_PER_BAR, TrackedBeats
from backend.analysis.snap import onset_strengths
from backend.analysis.tempo_range import TempoRange

OctaveChoice = Literal["kept", "doubled", "halved"]
# what the beats file says over the whole song
OctaveSummary = Literal["kept", "doubled", "halved", "mixed"]

# midpoint onsets at least this strong, against the weaker beats, are beats too
# the weaker beats and not all of them, so accented downbeats don't hide a real pulse
# tuned on clicks only. 0.7 eighth notes stay put, revisit with real songs
DOUBLE_SUPPORT = 0.8
# one parity of beats this much weaker than the other isn't beats, it's offbeats the tracker took
HALVE_SUPPORT = 0.4
# the weaker beats are this percentile of the beat onsets
WEAK_BEAT_PERCENTILE = 25.0
# a few beats aren't enough to judge, leave short tracks alone
MIN_BEATS = 8


@dataclass(frozen=True)
class OctaveCheck:
    choice: OctaveChoice
    # tempo from the median gap before the check, for the cli and the eval summary
    tracked_bpm: float
    # median midpoint onset over the weaker beats' onset
    midpoint_ratio: float
    # median onset of the weaker parity over the stronger one
    parity_ratio: float


def _bar_length(positions: np.ndarray, downbeats_known: bool) -> int:
    # madmom keeps one bar length per track, the librosa fallback assumes 4/4
    if not downbeats_known or len(positions) == 0:
        return FALLBACK_BEATS_PER_BAR
    return max(1, int(positions.max()))


def _positions_from(first_downbeat: int, count: int, bar_length: int) -> np.ndarray:
    return (np.arange(count, dtype=np.int64) - first_downbeat) % bar_length + 1


def _doubled(tracked: TrackedBeats) -> TrackedBeats:
    times = tracked.times_ms
    mids = (times[:-1] + times[1:]) / 2.0
    out = np.empty(2 * len(times) - 1)
    out[0::2] = times
    out[1::2] = mids
    # bars keep their beat count, so a bar now lasts half as long. the tracker's
    # first downbeat stays a downbeat
    downbeats = np.flatnonzero(tracked.positions == 1)
    first = 2 * int(downbeats[0]) if len(downbeats) else 0
    positions = _positions_from(first, len(out), _bar_length(tracked.positions, tracked.downbeats_known))
    return replace(tracked, times_ms=out, positions=positions)


def _halved(tracked: TrackedBeats, parity: int) -> TrackedBeats:
    times = tracked.times_ms[parity::2]
    kept = tracked.positions[parity::2]
    downbeats = np.flatnonzero(kept == 1)
    first = int(downbeats[0]) if len(downbeats) else 0
    positions = _positions_from(first, len(times), _bar_length(tracked.positions, tracked.downbeats_known))
    return replace(tracked, times_ms=times, positions=positions)


def check_octave(
    samples: np.ndarray,
    sample_rate: int,
    tracked: TrackedBeats,
    tempo_range: TempoRange = TempoRange(),
    shift_ms: float = 0.0,
    allow_change: bool = True,
) -> tuple[TrackedBeats, OctaveCheck]:
    """Double or halve the tracked beats once if the onsets clearly call for it.

    shift_ms is the tracker's bias correction, the same one snap uses, so the
    strengths are read around where the beats really are. allow_change=False
    only measures, the beats stay as tracked.
    """
    times = tracked.times_ms
    if len(times) < MIN_BEATS:
        return tracked, OctaveCheck("kept", 0.0, 0.0, 0.0)
    bpm = 60000.0 / float(np.median(np.diff(times)))

    at_beats = onset_strengths(samples, sample_rate, times + shift_ms)
    mids = (times[:-1] + times[1:]) / 2.0 + shift_ms
    at_mids = onset_strengths(samples, sample_rate, mids)

    weak = float(np.percentile(at_beats, WEAK_BEAT_PERCENTILE))
    midpoint_ratio = float(np.median(at_mids)) / weak if weak > 0 else 0.0
    even, odd = float(np.median(at_beats[0::2])), float(np.median(at_beats[1::2]))
    strong = max(even, odd)
    parity_ratio = min(even, odd) / strong if strong > 0 else 1.0

    def result(choice: OctaveChoice) -> OctaveCheck:
        return OctaveCheck(choice, bpm, midpoint_ratio, parity_ratio)

    if not allow_change:
        return tracked, result("kept")
    # halve first, an offbeat the tracker took for a beat also looks like a strong midpoint
    if parity_ratio < HALVE_SUPPORT and tempo_range.contains(bpm / 2.0):
        return _halved(tracked, 0 if even >= odd else 1), result("halved")
    if midpoint_ratio >= DOUBLE_SUPPORT and tempo_range.contains(bpm * 2.0):
        return _doubled(tracked), result("doubled")
    return tracked, result("kept")


def _slice(tracked: TrackedBeats, first: int, stop: int) -> TrackedBeats:
    return replace(tracked, times_ms=tracked.times_ms[first:stop], positions=tracked.positions[first:stop])


def check_octave_per_segment(
    samples: np.ndarray,
    sample_rate: int,
    tracked: TrackedBeats,
    ranges: list[tuple[int, int]],
    tempo_range: TempoRange = TempoRange(),
    shift_ms: float = 0.0,
    felt: list[bool] | None = None,
) -> tuple[TrackedBeats, list[OctaveCheck]]:
    """check_octave on each [first, stop) range of beats, joined back together.

    The ranges come from a rough tempo map of the raw beats. A range that stays as it was
    keeps the tracker's bar positions, a doubled or halved one gets them counted again.
    A range marked felt (a dotted or triplet section, see tempo_map.felt_sections) is only
    measured. Its beats can look like an octave off, a 3-3-2 rhythm leaves every other one
    without an onset, but the ratio check is what folds it back into the notated tempo.
    """
    parts: list[TrackedBeats] = []
    checks: list[OctaveCheck] = []
    felt = felt or [False] * len(ranges)
    for (first, stop), leave in zip(ranges, felt):
        part, check = check_octave(
            samples, sample_rate, _slice(tracked, first, stop), tempo_range, shift_ms, allow_change=not leave
        )
        parts.append(part)
        checks.append(check)
    joined = replace(
        tracked,
        times_ms=np.concatenate([p.times_ms for p in parts]),
        positions=np.concatenate([p.positions for p in parts]),
    )
    return joined, checks


def summary(checks: list[OctaveCheck]) -> OctaveSummary:
    changed = {c.choice for c in checks if c.choice != "kept"}
    if not changed:
        return "kept"
    if len(changed) == 1 and all(c.choice != "kept" for c in checks):
        return changed.pop()
    return "mixed"
