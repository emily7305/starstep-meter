"""Tempo fit: one straight line through the snapped beats.

time_ms = offset_ms + period_ms * index, least squares over the trimmed region.
The index is exact and the noise is all in the time, so time is regressed on
index. Index 0 is the first downbeat, which makes the intercept beat_offset_ms.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MIN_BEATS = 8
# beats further than this from the line are left out of the refit
# the mad term takes over on sloppy material so a slightly drifting song doesn't lose half its beats
OUTLIER_FLOOR_MS = 15.0
OUTLIER_MADS = 4.0
MAX_ROUNDS = 5
# first fit covers this many beats, then the span doubles until it covers everything
FIRST_SPAN_BEATS = 16
# confidence is the share of beats within this of the grid, a bit over one madmom frame
# a guess, revisit once there are real songs to look at
CONFIDENCE_TOLERANCE_MS = 10.0
# librosa has no downbeats, so its bar phase is a guess
NO_DOWNBEAT_CONFIDENCE_SCALE = 0.5


class GridFitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GridFit:
    period_ms: float
    # fitted time of index 0, the first downbeat
    offset_ms: float
    # grid index of every beat, 0 is the first downbeat, pickups are negative
    indices: np.ndarray
    residuals_ms: np.ndarray
    inliers: np.ndarray
    residual_rms_ms: float
    confidence: float

    @property
    def bpm(self) -> float:
        return 60000.0 / self.period_ms


def _line(indices: np.ndarray, times: np.ndarray) -> tuple[float, float]:
    # returns (intercept, slope), polyfit gives highest power first
    slope, intercept = np.polyfit(indices.astype(np.float64), times, 1)
    return float(intercept), float(slope)


def _round_and_fit(times: np.ndarray, intercept: float, period: float, use: np.ndarray) -> tuple[float, float, np.ndarray, np.ndarray]:
    indices = np.round((times - intercept) / period).astype(np.int64)
    residuals = times - (intercept + period * indices)
    centered = residuals[use] - np.median(residuals[use])
    limit = max(OUTLIER_FLOOR_MS, OUTLIER_MADS * 1.4826 * float(np.median(np.abs(centered))))
    inliers = use & (np.abs(residuals) <= limit)
    # two beats on one index can't both be right, keep the closer one
    for k in np.unique(indices[inliers]):
        same = np.flatnonzero(inliers & (indices == k))
        if len(same) > 1:
            inliers[same] = False
            inliers[same[np.argmin(np.abs(residuals[same]))]] = True
    if inliers.sum() < 2 or len(np.unique(indices[inliers])) < 2:
        raise GridFitError("beats don't line up on one steady tempo")
    intercept, period = _line(indices[inliers], times[inliers])
    return intercept, period, indices, inliers


def fit_grid(
    times_ms: np.ndarray,
    is_downbeat: np.ndarray,
    downbeats_known: bool = True,
) -> GridFit:
    times = np.asarray(times_ms, dtype=np.float64)
    downbeats = np.asarray(is_downbeat, dtype=bool)
    if len(times) < MIN_BEATS:
        raise GridFitError(f"need at least {MIN_BEATS} beats for a tempo fit, got {len(times)}")
    if np.any(np.diff(times) <= 0):
        raise GridFitError("beat times have to be strictly increasing")

    # rounding (t - t0) / period over the whole song needs a period that's already close,
    # 0.5% off puts the index a whole beat out after ~100 beats. so start on a short span
    # from the median gap and double it, each fit is precise enough for the next span
    # todo: stepping by local gaps was the first try, two neighbouring outliers broke it
    period = float(np.median(np.diff(times)))
    span = FIRST_SPAN_BEATS * period
    # the first beat could be an outlier itself, so start from the mean phase of the first span
    first = times <= times[0] + span
    phase = float(np.angle(np.mean(np.exp(2j * np.pi * (times[first] - times[0]) / period))))
    intercept = float(times[0]) + phase / (2.0 * np.pi) * period
    while True:
        use = times <= times[0] + span
        intercept, period, indices, inliers = _round_and_fit(times, intercept, period, use)
        if use.all():
            break
        span *= 2.0

    for _ in range(MAX_ROUNDS):
        intercept, period, indices, next_inliers = _round_and_fit(times, intercept, period, np.ones(len(times), dtype=bool))
        if next_inliers.sum() < MIN_BEATS:
            raise GridFitError("beats don't line up on one steady tempo")
        if np.array_equal(next_inliers, inliers):
            break
        inliers = next_inliers

    indices = np.round((times - intercept) / period).astype(np.int64)
    first_downbeat = int(indices[np.flatnonzero(downbeats)[0]]) if downbeats.any() else int(indices[0])
    indices = indices - first_downbeat
    offset = intercept + period * first_downbeat
    residuals = times - (offset + period * indices)

    rms = float(np.sqrt(np.mean(residuals[inliers] ** 2)))
    confidence = float(np.mean(np.abs(residuals) <= CONFIDENCE_TOLERANCE_MS))
    if not downbeats_known:
        confidence *= NO_DOWNBEAT_CONFIDENCE_SCALE

    return GridFit(
        period_ms=period,
        offset_ms=offset,
        indices=indices,
        residuals_ms=residuals,
        inliers=inliers,
        residual_rms_ms=rms,
        confidence=confidence,
    )
