"""A second opinion on the beats: librosa's tracker on the same audio, compared per tempo segment.

librosa's beats go through the same onset snap as the main tracker's, so on a clean attack both
land on the same onset and the distance between them is a fraction of a ms. A segment where the
two keep picking attacks further apart than max_disagreement_ms is flagged.

The comparison doesn't care about octave. librosa's own tempo guess can be half or twice the
main one, so the distance is taken both ways (every main beat to the nearest librosa beat, and
every librosa beat to the nearest main beat) and the smaller median is the one that counts.
Half or double tempo then agrees, half a beat off doesn't. Felt sections and off-beat runs are
left out, the trackers are expected to disagree there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from backend.analysis.beats import BeatTrackingError, track_beats
from backend.analysis.snap import DEFAULT_WINDOW_MS, snap_to_onsets
from backend.analysis.tempo_range import TempoRange

SECOND_TRACKER = "librosa"
# a segment needs this many compared beats for a verdict, fewer is the tracker barely there
MIN_COMPARED = 4


@dataclass(frozen=True)
class CrossCheckConfig:
    # two trackers snapped onto the same attack are under a ms apart. more than the snap window
    # means they took different attacks. a guess from click tracks, revisit on real songs
    max_disagreement_ms: float = 20.0

    def __post_init__(self) -> None:
        if not self.max_disagreement_ms > 0:
            raise ValueError("max_disagreement_ms has to be positive")


@dataclass(frozen=True)
class SegmentCheck:
    start_ms: float
    end_ms: float
    # median distance between the two trackers' beats, None with too few beats to compare
    disagreement_ms: float | None
    compared: int
    flagged: bool


@dataclass(frozen=True)
class CrossCheck:
    max_disagreement_ms: float
    segments: list[SegmentCheck]
    # every compared beat (from whichever side its segment was measured on) and whether the other
    # tracker had a beat within max_disagreement_ms of it. confidence reads these per window
    times_ms: np.ndarray
    agrees: np.ndarray


def second_opinion(
    samples: np.ndarray,
    sample_rate: int,
    start_ms: float,
    end_ms: float,
    tempo_range: TempoRange = TempoRange(),
    snap_window_ms: float = DEFAULT_WINDOW_MS,
) -> np.ndarray:
    """librosa's beats over the trim, snapped. Empty when it finds too few, the check just doesn't run then."""
    try:
        tracked = track_beats(samples, sample_rate, start_ms, end_ms, tracker=SECOND_TRACKER, tempo_range=tempo_range)
    except BeatTrackingError:
        return np.zeros(0)
    # librosa's late bias is well inside the window, same as when it's the main tracker
    snap = snap_to_onsets(samples, sample_rate, tracked.times_ms, window_ms=snap_window_ms, shift_ms=0.0)
    return np.asarray(snap.times_ms, dtype=np.float64)


def nearest_distance_ms(times: np.ndarray, others: np.ndarray) -> np.ndarray:
    """For every time, how far the nearest of others is. others has to be sorted."""
    times = np.asarray(times, dtype=np.float64)
    if len(others) == 0:
        return np.full(len(times), np.inf)
    i = np.searchsorted(others, times)
    before = others[np.clip(i - 1, 0, len(others) - 1)]
    after = others[np.clip(i, 0, len(others) - 1)]
    return np.minimum(np.abs(times - before), np.abs(after - times))


def _outside(times: np.ndarray, skip: Sequence[tuple[float, float]]) -> np.ndarray:
    keep = np.ones(len(times), dtype=bool)
    for a, b in skip:
        keep &= ~((times >= a) & (times <= b))
    return keep


def compare(
    main_ms: np.ndarray,
    second_ms: np.ndarray,
    segments: Sequence[tuple[float, float]],
    skip: Sequence[tuple[float, float]] = (),
    config: CrossCheckConfig = CrossCheckConfig(),
) -> CrossCheck:
    """Both trackers' beats per segment, segments as (start_ms, end_ms), skip as spans not to compare."""
    main = np.sort(np.asarray(main_ms, dtype=np.float64))
    second = np.sort(np.asarray(second_ms, dtype=np.float64))
    tol = config.max_disagreement_ms
    checks: list[SegmentCheck] = []
    times: list[np.ndarray] = []
    agrees: list[np.ndarray] = []
    for k, (start, end) in enumerate(segments):
        # the first and last segment run on past the trim points, beats can sit a hair outside them
        lo = -np.inf if k == 0 else start
        hi = np.inf if k == len(segments) - 1 else end
        a = main[(main >= lo) & (main < hi) & _outside(main, skip)]
        b = second[(second >= lo) & (second < hi) & _outside(second, skip)]
        sides = [(a, nearest_distance_ms(a, second)), (b, nearest_distance_ms(b, main))]
        sides = [(t, d) for t, d in sides if len(t) >= MIN_COMPARED]
        if not sides or len(b) < MIN_COMPARED:
            checks.append(SegmentCheck(start, end, None, 0, False))
            continue
        # the side whose beats the other tracker covers better is the octave both share
        t, d = min(sides, key=lambda side: float(np.median(side[1])))
        median = float(np.median(d))
        checks.append(SegmentCheck(start, end, median, len(t), median > tol))
        times.append(t)
        agrees.append(d <= tol)
    all_times = np.concatenate(times) if times else np.zeros(0)
    all_agrees = np.concatenate(agrees) if agrees else np.zeros(0, dtype=bool)
    order = np.argsort(all_times, kind="stable")
    return CrossCheck(tol, checks, all_times[order], all_agrees[order])
