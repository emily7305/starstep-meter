"""Tempo map: split the snapped beats into steady segments, one grid line each.

A segment boundary goes where one straight line (time against beat index)
stops explaining the beats: the bpm shifts, the phase jumps, or the residual
from a single line drifts past a threshold that two lines fix. Short
wobbles don't count, every segment needs min_segment_beats and every split
has to be clear of the noise. Each segment then gets its own fit_grid, so
its bpm and anchor (its first downbeat) come from its own beats only.

The thresholds are all in TempoMapConfig. They're tuned on synthetic beat
lists and click tracks only, see docs/decisions.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from backend.analysis.grid_fit import (
    CONFIDENCE_TOLERANCE_MS,
    MIN_BEATS,
    NO_DOWNBEAT_CONFIDENCE_SCALE,
    GridFit,
    GridFitError,
    fit_grid,
)


@dataclass(frozen=True)
class TempoMapConfig:
    # smoothed residual past this means one line doesn't hold the grid there. a bit under
    # the 10 ms confidence tolerance, tuned on synthetic jitter only, revisit with real songs
    residual_shift_ms: float = 8.0
    # neighbouring segments this far apart in bpm are a real change, 0.4% is 0.48 bpm at 120
    bpm_shift_ratio: float = 0.004
    # and any shift has to be this many standard errors out, so a short noisy side can't fake one
    shift_z: float = 5.0
    # residuals go through a running median this long first, a few odd beats aren't a drift
    smooth_beats: int = 7
    # two bars of 4/4. shorter changes get merged away, the ui can still split them by hand
    min_segment_beats: int = 8
    # how far a boundary may move when it's refined beat by beat
    refine_beats: int = 2

    def __post_init__(self) -> None:
        if self.residual_shift_ms <= 0 or self.bpm_shift_ratio <= 0 or self.shift_z <= 0:
            raise ValueError("tempo map thresholds have to be positive")
        if self.smooth_beats < 1:
            raise ValueError("smooth_beats has to be at least 1")
        # every segment goes through fit_grid, which needs this many beats
        if self.min_segment_beats < MIN_BEATS:
            raise ValueError(f"min_segment_beats has to be at least {MIN_BEATS}")
        if self.refine_beats < 0:
            raise ValueError("refine_beats can't be negative")


@dataclass(frozen=True)
class SegmentFit:
    # beats[first:stop] belong to this segment
    first: int
    stop: int
    start_ms: float
    end_ms: float
    fit: GridFit

    @property
    def anchor_ms(self) -> float:
        # the segment's first downbeat (or first beat), index 0 of its grid
        return self.fit.offset_ms


@dataclass(frozen=True)
class TempoMapResult:
    segments: list[SegmentFit]
    # per beat over the whole song, each against its own segment's grid
    residuals_ms: np.ndarray
    # grid index within the segment, 0 is the segment's anchor
    indices: np.ndarray
    segment_of_beat: np.ndarray
    inliers: np.ndarray
    downbeats_known: bool

    @property
    def residual_rms_ms(self) -> float:
        r = self.residuals_ms[self.inliers]
        return float(np.sqrt(np.mean(r**2))) if len(r) else 0.0

    @property
    def confidence(self) -> float:
        # same measure as each segment's, over the whole song
        share = float(np.mean(np.abs(self.residuals_ms) <= CONFIDENCE_TOLERANCE_MS))
        return share if self.downbeats_known else share * NO_DOWNBEAT_CONFIDENCE_SCALE


@dataclass(frozen=True)
class _Line:
    intercept: float
    slope: float
    sigma: float
    n: int
    x_mean: float
    sxx: float

    def at(self, x: np.ndarray | float) -> np.ndarray | float:
        return self.intercept + self.slope * x

    def slope_se(self) -> float:
        return self.sigma / np.sqrt(self.sxx)

    def at_se(self, x: float) -> float:
        return self.sigma * float(np.sqrt(1.0 / self.n + (x - self.x_mean) ** 2 / self.sxx))


# keeps the standard errors finite on perfectly clean synthetic beats
_SIGMA_FLOOR_MS = 0.05
# local period for the rough indices is the median of this many gaps around each beat
_LOCAL_GAPS = 9


def _line(x: np.ndarray, y: np.ndarray) -> _Line:
    x = x.astype(np.float64)
    x_mean, y_mean = float(x.mean()), float(y.mean())
    dx = x - x_mean
    sxx = float(np.dot(dx, dx))
    slope = float(np.dot(dx, y - y_mean) / sxx)
    intercept = y_mean - slope * x_mean
    resid = y - (intercept + slope * x)
    dof = max(1, len(x) - 2)
    sigma = max(_SIGMA_FLOOR_MS, float(np.sqrt(np.dot(resid, resid) / dof)))
    return _Line(intercept, slope, sigma, len(x), x_mean, sxx)


def rough_indices(times_ms: np.ndarray) -> np.ndarray:
    """Beat index from the gaps, good enough to find change points, not for the final fit.

    Each gap counts round(gap / local period) beats, with the local period the running
    median gap. A tempo change moves the median along with it.
    """
    gaps = np.diff(times_ms)
    if len(gaps) == 0:
        return np.zeros(len(times_ms), dtype=np.int64)
    half = _LOCAL_GAPS // 2
    padded = np.pad(gaps, half, mode="edge")
    local = np.median(sliding_window_view(padded, 2 * half + 1), axis=1)
    steps = np.maximum(1, np.round(gaps / local)).astype(np.int64)
    return np.concatenate(([0], np.cumsum(steps)))


def _systematic(residuals: np.ndarray, window: int) -> float:
    # largest running median of the residuals, so single odd beats don't count as drift
    if len(residuals) == 0:
        return 0.0
    if len(residuals) <= window:
        return float(abs(np.median(residuals)))
    return float(np.abs(np.median(sliding_window_view(residuals, window), axis=1)).max())


def _sse_split(x: np.ndarray, y: np.ndarray, m: int) -> int | None:
    # the cut j (1..n-1) that minimises the two lines' squared error, both sides at least m long
    n = len(x)
    if n < 2 * m:
        return None
    x = x.astype(np.float64)
    # centred on the range so the prefix sums don't lose precision on long songs
    x = x - x.mean()
    y = y - y.mean()
    zero = np.zeros(1)
    c = {k: np.concatenate((zero, np.cumsum(v))) for k, v in {"1": np.ones(n), "x": x, "y": y, "xx": x * x, "xy": x * y, "yy": y * y}.items()}

    def sse(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        cnt = c["1"][hi] - c["1"][lo]
        sx, sy = c["x"][hi] - c["x"][lo], c["y"][hi] - c["y"][lo]
        sxx = c["xx"][hi] - c["xx"][lo] - sx * sx / cnt
        sxy = c["xy"][hi] - c["xy"][lo] - sx * sy / cnt
        syy = c["yy"][hi] - c["yy"][lo] - sy * sy / cnt
        return syy - np.where(sxx > 0, sxy * sxy / np.where(sxx > 0, sxx, 1.0), 0.0)

    cuts = np.arange(m, n - m + 1)
    total = sse(np.zeros_like(cuts), cuts) + sse(cuts, np.full_like(cuts, n))
    return int(cuts[np.argmin(total)])


@dataclass(frozen=True)
class _Verdict:
    justified: bool
    # how far past the nearest threshold, for picking which boundary to merge first
    evidence: float
    # phase jump at the cut in whole beats, nonzero means the rough indices slipped there
    index_slip: int
    # one line over the whole range drifts past residual_shift_ms somewhere
    one_line_fails: bool


def _judge(x: np.ndarray, y: np.ndarray, j: int, config: TempoMapConfig) -> _Verdict:
    """Is a boundary before beat j of this range a real change?"""
    left, right = _line(x[:j], y[:j]), _line(x[j:], y[j:])
    period = 0.5 * (left.slope + right.slope)
    z = config.shift_z

    d_slope = abs(right.slope - left.slope)
    slope_se = float(np.hypot(left.slope_se(), right.slope_se()))
    bpm_sig = d_slope > z * slope_se
    bpm_ratio = d_slope / left.slope

    # phase jump where the right side starts, folded onto the nearest whole beat. a jump of
    # exactly one beat is the same grid, either a slipped rough index or a beat the song left out
    x0 = float(x[j])
    jump = float(right.at(x0) - left.at(x0))
    slip = int(np.round(jump / period))
    folded = abs(jump - slip * period)
    jump_se = float(np.hypot(left.at_se(x0), right.at_se(x0)))
    jump_sig = folded > z * jump_se

    whole = _line(x, y)
    sys_whole = _systematic(y - whole.at(x), config.smooth_beats)
    sys_sides = max(_systematic(y[:j] - left.at(x[:j]), config.smooth_beats), _systematic(y[j:] - right.at(x[j:]), config.smooth_beats))
    # a slow drift: each bpm difference is under the ratio, but one line can't hold the grid
    residual_fix = sys_whole > config.residual_shift_ms and sys_sides <= 0.5 * sys_whole

    big_bpm = bpm_ratio > config.bpm_shift_ratio and bpm_sig
    big_jump = folded > config.residual_shift_ms and jump_sig
    justified = big_bpm or big_jump or (residual_fix and (bpm_sig or jump_sig))
    evidence = max(bpm_ratio / config.bpm_shift_ratio, folded / config.residual_shift_ms, sys_whole / config.residual_shift_ms)
    return _Verdict(justified, evidence, slip, sys_whole > config.residual_shift_ms)


def _one_line_fails(x: np.ndarray, y: np.ndarray, config: TempoMapConfig) -> bool:
    line = _line(x, y)
    return _systematic(y - line.at(x), config.smooth_beats) > config.residual_shift_ms


def _split(x: np.ndarray, y: np.ndarray, a: int, b: int, config: TempoMapConfig) -> list[tuple[int, int]]:
    # splits generously and leaves it to _merge to drop the boundaries that don't hold up.
    # the best single cut of a fast-slow-fast song leaves one side mixed, so judging that
    # one cut alone would stop too early
    m = config.min_segment_beats
    # rough indices can slip by a whole beat (two displaced beats next to each other), which
    # looks like a phase jump. repair the slip and look again, a few times at most
    for _ in range(4):
        j = _sse_split(x[a:b], y[a:b], m)
        if j is None:
            return [(a, b)]
        verdict = _judge(x[a:b], y[a:b], j, config)
        if verdict.index_slip in (-1, 1) and not verdict.justified:
            # the right side's indices ran ahead by the slip, so its line came out a whole beat early.
            # only kept if one line fits again afterwards, a mixed side can look like a slip too
            trial = x[a:b].copy()
            trial[j:] += verdict.index_slip
            if not _one_line_fails(trial, y[a:b], config):
                x[a + j:] += verdict.index_slip
                continue
        if verdict.justified or verdict.one_line_fails:
            cut = a + j
            return _split(x, y, a, cut, config) + _split(x, y, cut, b, config)
        return [(a, b)]
    return [(a, b)]


def _fluctuation(x: np.ndarray, y: np.ndarray, ranges: list[tuple[int, int]], config: TempoMapConfig) -> int | None:
    # a middle segment the song comes back out of onto the old grid, like a few rushed beats.
    # the beats either side sit on one line together, unfolded, so no beat got lost or added.
    # a real short section at another tempo leaves the grid after it shifted
    best: int | None = None
    for k in range(1, len(ranges) - 1):
        (a, _), (mid_a, mid_b), (_, b) = ranges[k - 1], ranges[k], ranges[k + 1]
        outer = np.r_[a:mid_a, mid_b:b]
        if not _one_line_fails(x[outer], y[outer], config):
            if best is None or mid_b - mid_a < ranges[best][1] - ranges[best][0]:
                best = k
    return best


def _merge(x: np.ndarray, y: np.ndarray, ranges: list[tuple[int, int]], config: TempoMapConfig) -> list[tuple[int, int]]:
    # a boundary that made sense against the whole parent range might not against its
    # final neighbours, so check each one again and merge the weakest until all hold
    ranges = list(ranges)
    while len(ranges) > 1:
        k = _fluctuation(x, y, ranges, config)
        if k is not None:
            ranges[k - 1:k + 2] = [(ranges[k - 1][0], ranges[k + 1][1])]
            continue
        weakest: tuple[float, int] | None = None
        for k in range(len(ranges) - 1):
            a, j = ranges[k]
            _, b = ranges[k + 1]
            verdict = _judge(x[a:b], y[a:b], j - a, config)
            if not verdict.justified and (weakest is None or verdict.evidence < weakest[0]):
                weakest = (verdict.evidence, k)
        if weakest is None:
            break
        k = weakest[1]
        ranges[k:k + 2] = [(ranges[k][0], ranges[k + 1][1])]
    return ranges


def _reoptimize(x: np.ndarray, y: np.ndarray, ranges: list[tuple[int, int]], config: TempoMapConfig) -> list[tuple[int, int]]:
    # a cut made while a range still held three tempos can sit a few beats off, and the merge
    # keeps it where it was. find each boundary again between its final neighbours
    out = list(ranges)
    for _ in range(3):
        moved = False
        for k in range(len(out) - 1):
            a, b = out[k][0], out[k + 1][1]
            j = _sse_split(x[a:b], y[a:b], config.min_segment_beats)
            if j is not None and a + j != out[k][1]:
                out[k], out[k + 1] = (a, a + j), (a + j, b)
                moved = True
        if not moved:
            break
    return out


def _refine(x: np.ndarray, y: np.ndarray, ranges: list[tuple[int, int]], config: TempoMapConfig) -> list[tuple[int, int]]:
    # the sse cut can land a beat off, mostly on the junction beat, which sits on both lines
    # when the tempo changes without a phase jump. fit each side away from the cut, then
    # give every beat near it to the line it sits on. ties go right, a chart puts the
    # bpm change on the first beat of the new tempo
    r = config.refine_beats
    out = list(ranges)
    for k in range(len(out) - 1):
        a, j = out[k]
        _, b = out[k + 1]
        lo, hi = max(a + MIN_BEATS, j - r), min(b - MIN_BEATS, j + r)
        if lo > hi:
            continue
        left = _line(x[a:max(a + 2, j - r)], y[a:max(a + 2, j - r)])
        right = _line(x[min(b - 2, j + r):b], y[min(b - 2, j + r):b])
        costs = {
            cut: float(np.abs(y[lo:cut] - left.at(x[lo:cut])).sum() + np.abs(y[cut:hi] - right.at(x[cut:hi])).sum())
            for cut in range(lo, hi + 1)
        }
        # within one noise sigma of the best counts as a tie
        tie = max(left.sigma, right.sigma)
        best = min(costs.values())
        cut = min(c for c, cost in costs.items() if cost <= best + tie)
        out[k] = (a, cut)
        out[k + 1] = (cut, b)
    return out


def build_tempo_map(
    times_ms: np.ndarray,
    is_downbeat: np.ndarray,
    start_ms: float,
    end_ms: float,
    downbeats_known: bool = True,
    config: TempoMapConfig = TempoMapConfig(),
) -> TempoMapResult:
    """Segments over [start_ms, end_ms], usually the trim points, with one fit per segment."""
    times = np.asarray(times_ms, dtype=np.float64)
    downbeats = np.asarray(is_downbeat, dtype=bool)
    if len(times) < MIN_BEATS:
        raise GridFitError(f"need at least {MIN_BEATS} beats for a tempo fit, got {len(times)}")
    if np.any(np.diff(times) <= 0):
        raise GridFitError("beat times have to be strictly increasing")

    x = rough_indices(times).astype(np.float64)
    ranges = _split(x, times, 0, len(times), config)
    ranges = _merge(x, times, ranges, config)
    ranges = _reoptimize(x, times, ranges, config)
    ranges = _refine(x, times, ranges, config)

    fits: list[GridFit] = []
    k = 0
    while k < len(ranges):
        a, b = ranges[k]
        try:
            fits.append(fit_grid(times[a:b], downbeats[a:b], downbeats_known=downbeats_known))
            k += 1
        except GridFitError:
            # too messy for its own line, fold it into a neighbour and fit again
            if len(ranges) == 1:
                raise
            if k + 1 < len(ranges):
                ranges[k:k + 2] = [(a, ranges[k + 1][1])]
            else:
                ranges[k - 1:k + 1] = [(ranges[k - 1][0], b)]
                fits.pop()
                k -= 1

    segments: list[SegmentFit] = []
    for k, ((a, b), fit) in enumerate(zip(ranges, fits)):
        # a later segment starts on its own grid at its first beat, where a chart would put the bpm change
        seg_start = start_ms if k == 0 else fit.offset_ms + fit.period_ms * float(fit.indices[0])
        segments.append(SegmentFit(first=a, stop=b, start_ms=seg_start, end_ms=end_ms, fit=fit))
    for k in range(len(segments) - 1):
        nxt = segments[k + 1]
        segments[k] = SegmentFit(segments[k].first, segments[k].stop, segments[k].start_ms, nxt.start_ms, segments[k].fit)

    residuals = np.concatenate([s.fit.residuals_ms for s in segments])
    indices = np.concatenate([s.fit.indices for s in segments])
    inliers = np.concatenate([s.fit.inliers for s in segments])
    segment_of_beat = np.concatenate([np.full(s.stop - s.first, i, dtype=np.int64) for i, s in enumerate(segments)])
    return TempoMapResult(
        segments=segments,
        residuals_ms=residuals,
        indices=indices,
        segment_of_beat=segment_of_beat,
        inliers=inliers,
        downbeats_known=downbeats_known,
    )
