"""A second opinion on the beats: librosa's tracker on the same audio, compared per tempo segment.

librosa runs on each tempo segment on its own, at that segment's bpm. Its beat tracker holds one
tempo, over a whole song it can't follow a tempo change and disagreed with every right one. So
the question it answers is the phase: which attacks it picks at that tempo. Its beats go through
the same onset snap as the main tracker's, so on a clean attack both land on the same onset and
the distance between them is a fraction of a ms. A segment where the two keep picking attacks
further apart than max_disagreement_ms is flagged.

The distance is taken both ways (every main beat to the nearest librosa beat, and every librosa
beat to the nearest main beat) and the smaller median counts, so a tracker that skips every
other beat still agrees and half a beat off doesn't. Felt sections and off-beat runs are left
out, the trackers are expected to disagree there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import librosa
import numpy as np

from backend.analysis.beats import PAD_S
from backend.analysis.snap import DEFAULT_WINDOW_MS, snap_to_onsets
from backend.analysis.tempo import onset_hop

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
    segments: Sequence[tuple[float, float, float]],
    snap_window_ms: float = DEFAULT_WINDOW_MS,
) -> np.ndarray:
    """librosa's beats over each (start_ms, end_ms, bpm) segment at that bpm, snapped. Empty when it finds none."""
    hop = onset_hop(sample_rate)
    found: list[np.ndarray] = []
    for start, end, bpm in segments:
        # the same padding the main tracker gets, so the first attack is seen in context
        lo = max(0, int(round((start / 1000.0 - PAD_S) * sample_rate)))
        hi = min(len(samples), int(round((end / 1000.0 + PAD_S) * sample_rate)))
        if hi - lo < 8 * hop:
            continue
        env = librosa.onset.onset_strength(y=samples[lo:hi], sr=sample_rate, hop_length=hop)
        _, frames = librosa.beat.beat_track(onset_envelope=env, sr=sample_rate, hop_length=hop, bpm=bpm, trim=False)
        t = librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop) * 1000.0 + lo / sample_rate * 1000.0
        found.append(t[(t >= start) & (t < end)])
    times = np.sort(np.concatenate(found)) if found else np.zeros(0)
    if len(times) == 0:
        return times
    # librosa's late bias is well inside the window, same as when it's the main tracker
    snap = snap_to_onsets(samples, sample_rate, times, window_ms=snap_window_ms, shift_ms=0.0)
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
