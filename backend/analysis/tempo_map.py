"""Tempo map: split the snapped beats into steady segments, one grid line each.

A segment boundary goes where one straight line (time against beat index)
stops explaining the beats: the bpm shifts, the phase jumps, or the residual
from a single line drifts past a threshold that two lines fix. Short
wobbles don't count, every segment needs min_segment_beats and every split
has to be clear of the noise. Each segment then gets its own fit_grid, so
its bpm and anchor (its first downbeat) come from its own beats only.

Then a consolidation pass merges what a chart wouldn't split: a section at a
dotted or triplet ratio of the tempo around it whose beats still land on that
tempo's grid, a short piece a bit off its neighbour, and a first or last
segment the tracker gave up on. A ratio merge is kept as a note on the
segment, so it can be split back out by hand.

The thresholds are all in TempoMapConfig. They're tuned on synthetic beat
lists, click tracks and one real song so far, see docs/decisions.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from fractions import Fraction

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
    # residuals go through a running median this long first, a few odd beats aren't a drift.
    # 16 is four bars of 4/4: a real song's beats sit off the grid for up to ~4 beats at a time
    # (fills, a different instrument taking the attack), 7 called that a drift
    smooth_beats: int = 16
    # two bars of 4/4. shorter changes get merged away, the ui can still split them by hand
    min_segment_beats: int = 8
    # how far a boundary may move when it's refined beat by beat
    refine_beats: int = 2
    # ratio check: a segment within this of a simple ratio of a longer neighbour's bpm is a
    # candidate for being that neighbour's tempo felt differently (dotted, triplet feel)
    ratio_tolerance: float = 0.005
    # the simple ratios are q/p: its beats land every p steps of 1/q of the neighbour's beat, q
    # one of these subdivisions and p up to the largest, within half and double time. that
    # gives 1/2, 3/5, 2/3, 3/4, 4/5, 6/5, 4/3, 3/2 and 2
    ratio_subdivisions: tuple[int, ...] = (1, 2, 3, 4, 6)
    # a beat counts as on a grid point within this, same as the confidence tolerance
    ratio_hit_ms: float = 10.0
    # it merges when the neighbour's grid, extended at the same phase with its halves, thirds and
    # 1/numerator of the ratio, catches at least this share of what the segment's own lines catch
    ratio_fit_min: float = 0.8
    # short segments: under max(short_min_ms, short_min_bars of 4/4) and within short_bpm_ratio
    # of a neighbour, they're the start or end of the neighbour's tempo that came out a bit off
    short_min_ms: float = 4000.0
    short_min_bars: float = 8.0
    short_bpm_ratio: float = 0.02
    # weak first or last segment: its beats cover less than this share of its span (the tracker
    # gave up in a fade), or its median loudness is this far under the song's
    weak_coverage: float = 0.6
    weak_energy_db: float = -12.0
    # a felt section at the very start or end has only one neighbour to carry it, so it has to
    # be short, under this share of the song or this many bars of 4/4, whichever is longer,
    # and fit at least edge_fit_min. a modulation that runs to the end is longer than that
    edge_max_share: float = 0.1
    edge_max_bars: float = 8.0
    edge_fit_min: float = 0.9
    # two or more short segments in a row fold in when the segment after them sits on the lines
    # of the one before (or the other way round), this share of what its own lines catch
    run_fit_min: float = 0.8

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
        if not 0 < self.ratio_tolerance < 0.05 or self.ratio_hit_ms <= 0 or not 0 < self.ratio_fit_min <= 1:
            raise ValueError("ratio check thresholds are out of range")
        if self.short_min_ms < 0 or self.short_min_bars < 0 or not 0 <= self.short_bpm_ratio < 0.5:
            raise ValueError("short segment thresholds are out of range")
        if not 0 <= self.weak_coverage <= 1 or self.weak_energy_db > 0:
            raise ValueError("weak segment thresholds are out of range")
        if not self.ratio_subdivisions or any(q < 1 for q in self.ratio_subdivisions):
            raise ValueError("ratio_subdivisions has to be a list of whole numbers from 1")
        if not 0 <= self.edge_max_share < 0.5 or self.edge_max_bars < 0 or not 0 < self.edge_fit_min <= 1:
            raise ValueError("edge thresholds are out of range")
        if not 0 < self.run_fit_min <= 1:
            raise ValueError("run_fit_min is out of range")


@dataclass(frozen=True)
class RatioMerge:
    """A segment the ratio check folded into its neighbour, kept so it can be split back by hand."""

    start_ms: float
    end_ms: float
    # what it fitted to on its own
    bpm: float
    # its bpm over the neighbour's, near enough
    ratio: Fraction
    # how well the neighbour's extended grid caught its beats, against its own grid
    fit: float


@dataclass(frozen=True)
class SegmentFit:
    # beats[first:stop] belong to this segment
    first: int
    stop: int
    start_ms: float
    end_ms: float
    fit: GridFit
    ratio_merges: tuple[RatioMerge, ...] = ()

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
    # real beats stay off the grid for a few beats in a row (lag 1 autocorrelation about 0.67 on
    # a real song), which makes white-noise standard errors far too small. widen sigma by the
    # usual ar(1) factor so the shift tests don't call that wobble significant
    rho = _lag1(resid)
    sigma *= float(np.sqrt((1.0 + rho) / (1.0 - rho)))
    return _Line(intercept, slope, sigma, len(x), x_mean, sxx)


# past this the ar(1) factor runs off to infinity on residuals that are really a trend
_MAX_LAG1 = 0.9


def _lag1(resid: np.ndarray) -> float:
    if len(resid) < 4:
        return 0.0
    centred = resid - resid.mean()
    energy = float(np.dot(centred, centred))
    if energy <= 0.0:
        return 0.0
    return min(_MAX_LAG1, max(0.0, float(np.dot(centred[:-1], centred[1:]) / energy)))


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


def felt_ratios(subdivisions: tuple[int, ...]) -> tuple[Fraction, ...]:
    """Every q/p within half and double time, q from subdivisions and p up to the largest of them."""
    out: set[Fraction] = set()
    for q in subdivisions:
        for p in range(1, max(subdivisions) + 1):
            r = Fraction(q, p)
            # in lowest terms its numerator has to be a subdivision too, 2/4 is 1/2 on whole beats
            if r.numerator in subdivisions and Fraction(1, 2) <= r <= 2 and r != 1:
                out.add(r)
    return tuple(sorted(out))


# the ratios a felt tempo has to the notated one in practice: half and double time, dotted
# (2/3, 3/2), triplet feel (3/4, 4/3), and the fives a tracker finds in sixths (6/5) or
# quarters (4/5)
RATIOS = felt_ratios(TempoMapConfig().ratio_subdivisions)
# beats per bar assumed for the short rule, there's no meter yet
_BAR_BEATS = 4


@dataclass
class _Piece:
    first: int
    stop: int
    fit: GridFit
    # beat ranges the grid was extended over without fitting them (ratio and weak merges)
    excluded: list[tuple[int, int]] = field(default_factory=list)
    # (first, stop, numerator of the ratio) of every ratio merge, for the residuals of those beats
    subdivided: list[tuple[int, int, int]] = field(default_factory=list)
    merges: list[RatioMerge] = field(default_factory=list)


def _kept(first: int, stop: int, excluded: list[tuple[int, int]]) -> np.ndarray:
    keep = np.ones(stop - first, dtype=bool)
    for a, b in excluded:
        keep[max(a, first) - first:max(min(b, stop) - first, 0)] = False
    return keep


def _fit_piece(
    times: np.ndarray,
    downbeats: np.ndarray,
    first: int,
    stop: int,
    excluded: list[tuple[int, int]],
    subdivided: list[tuple[int, int, int]],
    downbeats_known: bool,
) -> GridFit:
    """fit_grid on the beats that set this piece's tempo, with indices and residuals for all of them."""
    keep = _kept(first, stop, excluded)
    t = times[first:stop]
    if keep.sum() < MIN_BEATS:
        keep[:] = True
    core = fit_grid(t[keep], downbeats[first:stop][keep], downbeats_known=downbeats_known)
    period, offset = core.period_ms, core.offset_ms
    indices = np.round((t - offset) / period).astype(np.int64)
    indices[keep] = core.indices
    residuals = _residuals(t, first, offset, period, indices, subdivided)
    inliers = np.zeros(len(t), dtype=bool)
    inliers[keep] = core.inliers
    return GridFit(
        period_ms=period,
        offset_ms=offset,
        indices=indices,
        residuals_ms=residuals,
        inliers=inliers,
        residual_rms_ms=core.residual_rms_ms,
        confidence=core.confidence,
    )


def _residuals(
    t: np.ndarray, first: int, offset: float, period: float, indices: np.ndarray, subdivided: list[tuple[int, int, int]]
) -> np.ndarray:
    residuals = t - (offset + period * indices)
    for a, b, numerator in subdivided:
        # a beat folded in by the ratio check sits on a subdivision, measure it against that
        lo, hi = a - first, b - first
        residuals[lo:hi] = _off_subdivision(t[lo:hi], offset, period, numerator)
    return residuals


def _off_subdivision(times: np.ndarray, offset: float, period: float, numerator: int) -> np.ndarray:
    # signed ms to the nearest line, half or third of a grid, or 1/numerator of the ratio it was
    # felt at. a dotted rhythm lands on the halves of the notated beat, a triplet feel on the
    # thirds, a dotted eighth pulse (4/3) on the quarters
    d = (times - offset) / period
    best = np.full(len(d), np.inf)
    for sub in sorted({2, 3, numerator}):
        off = (sub * d - np.round(sub * d)) / sub
        best = np.where(np.abs(off) < np.abs(best), off, best)
    return best * period


def _hit_share(off_ms: np.ndarray, tol: float) -> float:
    return float(np.mean(np.abs(off_ms) <= tol)) if len(off_ms) else 0.0


def _near_ratio(ratio: float, tolerance: float, candidates: tuple[Fraction, ...] = RATIOS) -> Fraction | None:
    for candidate in candidates:
        if abs(ratio / float(candidate) - 1.0) <= tolerance:
            return candidate
    return None


class _Consolidator:
    """Merges what segmentation split but a chart wouldn't: felt tempos, short wobbles, weak edges."""

    def __init__(
        self,
        times: np.ndarray,
        downbeats: np.ndarray,
        start_ms: float,
        end_ms: float,
        downbeats_known: bool,
        config: TempoMapConfig,
        loudness: Callable[[float, float], float] | None,
    ) -> None:
        self.times = times
        self.downbeats = downbeats
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.downbeats_known = downbeats_known
        self.config = config
        self.loudness = loudness
        self.ratios = felt_ratios(config.ratio_subdivisions)

    def piece(self, first: int, stop: int, excluded=None, subdivided=None, merges=None) -> _Piece:
        excluded = list(excluded or [])
        subdivided = list(subdivided or [])
        fit = _fit_piece(self.times, self.downbeats, first, stop, excluded, subdivided, self.downbeats_known)
        return _Piece(first, stop, fit, excluded, subdivided, list(merges or []))

    def span(self, pieces: list[_Piece], k: int) -> tuple[float, float]:
        p = pieces[k]
        start = self.start_ms if k == 0 else float(self.times[p.first])
        end = self.end_ms if k == len(pieces) - 1 else float(self.times[p.stop])
        return start, end

    def own_beats(self, p: _Piece) -> np.ndarray:
        return self.times[p.first:p.stop][_kept(p.first, p.stop, p.excluded)]

    def absorb(self, pieces: list[_Piece], k: int, into: int, merge: RatioMerge | None) -> None:
        # the neighbour keeps its grid, the absorbed beats are left out of its fit
        s, n = pieces[k], pieces[into]
        excluded = n.excluded + [(s.first, s.stop)]
        subdivided = n.subdivided + s.subdivided + ([(s.first, s.stop, merge.ratio.numerator)] if merge is not None else [])
        merges = n.merges + s.merges + ([merge] if merge is not None else [])
        joined = self.piece(min(s.first, n.first), max(s.stop, n.stop), excluded, subdivided, merges)
        lo = min(k, into)
        pieces[lo:lo + 2] = [joined]

    def join(self, pieces: list[_Piece], k: int) -> None:
        # one tempo across both, fitted again over everything either of them fitted
        a, b = pieces[k], pieces[k + 1]
        joined = self.piece(a.first, b.stop, a.excluded + b.excluded, a.subdivided + b.subdivided, a.merges + b.merges)
        pieces[k:k + 2] = [joined]

    def song_ms(self) -> float:
        return max(self.end_ms - self.start_ms, 1e-9)

    def length_ms(self, pieces: list[_Piece], k: int) -> float:
        start, end = self.span(pieces, k)
        return end - start

    def own_share(self, s: _Piece) -> float:
        beats = self.own_beats(s)
        d = (beats - s.fit.offset_ms) / s.fit.period_ms
        return _hit_share((d - np.round(d)) * s.fit.period_ms, self.config.ratio_hit_ms)

    def ratio_score(self, s: _Piece, n: _Piece) -> tuple[Fraction, float] | None:
        """The ratio of s to n and how well n's grid, carried on through s, catches s's beats."""
        ratio = _near_ratio(s.fit.bpm / n.fit.bpm, self.config.ratio_tolerance, self.ratios)
        own = self.own_share(s)
        if ratio is None or own <= 0.0:
            return None
        # when the neighbour's tempo carries on underneath, the beats land on its lines, halves,
        # thirds or 1/numerator (sixths for 6/5). a tracker following a 3-3-2 rhythm puts beats
        # on the halves and fills the gaps with its own guesses, so its own line can do worse
        off = _off_subdivision(self.own_beats(s), n.fit.offset_ms, n.fit.period_ms, ratio.numerator)
        return ratio, _hit_share(off, self.config.ratio_hit_ms) / own

    def near_edge(self, pieces: list[_Piece], k: int, n: _Piece) -> bool:
        # short enough to be an intro or outro feel rather than a section of its own
        bars = self.config.edge_max_bars * _BAR_BEATS * n.fit.period_ms
        return self.length_ms(pieces, k) <= max(self.config.edge_max_share * self.song_ms(), bars)

    def stub(self, pieces: list[_Piece], k: int) -> int | None:
        # a short first or last segment at the same tempo as the other side of k: the song's own
        # tempo cut short by the edge, like an intro the tracker hadn't settled into yet
        for j, other in ((k - 1, k + 1), (k + 1, k - 1)):
            if j in (0, len(pieces) - 1) and self.short(pieces, j):
                if abs(pieces[j].fit.bpm / pieces[other].fit.bpm - 1.0) <= self.config.short_bpm_ratio:
                    return j
        return None

    def ratio_merge(self, pieces: list[_Piece]) -> bool:
        best: tuple[float, int, int, Fraction] | None = None
        # only a segment with a neighbour on both sides. a felt section sits inside the notated
        # tempo and the song comes back out of it, a modulation that runs to the end doesn't
        for k in range(1, len(pieces) - 1):
            s = pieces[k]
            sides = [k - 1, k + 1]
            stub = self.stub(pieces, k)
            if stub is not None:
                other = 2 * k - stub
                # next to a stub only the other side carries it, so it's held to the edge's length
                if self.near_edge(pieces, k, pieces[other]):
                    sides = [other]
            scores: list[tuple[float, int, Fraction]] = []
            for j in sides:
                n = pieces[j]
                # the longer side is the notated tempo, the shorter one is what got felt differently
                found = self.ratio_score(s, n)
                if found is None or n.stop - n.first <= s.stop - s.first:
                    break
                ratio, score = found
                scores.append((score, j, ratio))
            else:
                # both sides have to carry it, one that doesn't means the phase really moved there
                if min(score for score, _, _ in scores) >= self.config.ratio_fit_min:
                    score, j, ratio = max(scores, key=lambda item: item[0])
                    if best is None or score > best[0]:
                        best = (score, k, j, ratio)
        if best is None:
            return False
        score, k, j, ratio = best
        self.fold(pieces, k, j, ratio, score)
        return True

    def fold(self, pieces: list[_Piece], k: int, j: int, ratio: Fraction, score: float) -> None:
        start, end = self.span(pieces, k)
        merge = RatioMerge(start_ms=start, end_ms=end, bpm=pieces[k].fit.bpm, ratio=ratio, fit=score)
        self.absorb(pieces, k, j, merge)

    def edge_fold(self, pieces: list[_Piece]) -> bool:
        # a felt section at the very start or end, with one neighbour. stricter than in the middle
        # since nothing on the other side says the song comes back out of it
        if len(pieces) < 2:
            return False
        for k, j in ((0, 1), (len(pieces) - 1, len(pieces) - 2)):
            s, n = pieces[k], pieces[j]
            if n.stop - n.first <= s.stop - s.first or not self.near_edge(pieces, k, n):
                continue
            found = self.ratio_score(s, n)
            if found is not None and found[1] >= self.config.edge_fit_min:
                self.fold(pieces, k, j, *found)
                return True
        return False

    def short_run(self, pieces: list[_Piece]) -> bool:
        # two or more short segments in a row, where the tracker lost the beat for a few seconds
        # (215 then 203 in a 220 song) and found it again on the same grid afterwards
        k = 1
        while k < len(pieces) - 1:
            m = k
            while m < len(pieces) - 1 and self.short(pieces, m):
                m += 1
            if m - k >= 2 and m < len(pieces):
                left, right = pieces[k - 1], pieces[m]
                same = abs(right.fit.bpm / left.fit.bpm - 1.0) <= self.config.bpm_shift_ratio
                if same and not self.short(pieces, k - 1) and not self.short(pieces, m):
                    # the longer side's lines, carried through the run, have to catch the other
                    # side's beats about as well as its own lines do. whole beats lost inside the
                    # run don't matter, only that the grid comes out on the same lines
                    ref, other = (left, right) if left.stop - left.first >= right.stop - right.first else (right, left)
                    beats = self.own_beats(other)
                    d = (beats - ref.fit.offset_ms) / ref.fit.period_ms
                    own = self.own_share(other)
                    on = _hit_share((d - np.round(d)) * ref.fit.period_ms, self.config.ratio_hit_ms)
                    if own > 0.0 and on / own >= self.config.run_fit_min:
                        run = (pieces[k].first, pieces[m - 1].stop)
                        excluded = left.excluded + right.excluded + [run]
                        merges = [mg for piece in pieces[k - 1:m + 1] for mg in piece.merges]
                        joined = self.piece(left.first, right.stop, excluded, left.subdivided + right.subdivided, merges)
                        pieces[k - 1:m + 1] = [joined]
                        return True
            k = max(m, k + 1)
        return False

    def weak_edge(self, pieces: list[_Piece]) -> bool:
        if len(pieces) < 2:
            return False
        for k, j in ((len(pieces) - 1, len(pieces) - 2), (0, 1)):
            s = pieces[k]
            if pieces[j].stop - pieces[j].first <= s.stop - s.first:
                continue
            start, end = self.span(pieces, k)
            coverage = (s.stop - s.first) * s.fit.period_ms / max(end - start, 1e-9)
            quiet = self.loudness is not None and self.loudness(start, end) <= self.config.weak_energy_db
            if coverage < self.config.weak_coverage or quiet:
                self.absorb(pieces, k, j, None)
                return True
        return False

    def short(self, pieces: list[_Piece], k: int) -> bool:
        start, end = self.span(pieces, k)
        period = pieces[k].fit.period_ms
        return end - start < max(self.config.short_min_ms, self.config.short_min_bars * _BAR_BEATS * period)

    def short_merge(self, pieces: list[_Piece]) -> bool:
        candidates: list[tuple[float, int, int]] = []
        for k, s in enumerate(pieces):
            if not self.short(pieces, k):
                continue
            for j in (k - 1, k + 1):
                if 0 <= j < len(pieces):
                    off = abs(s.fit.bpm / pieces[j].fit.bpm - 1.0)
                    if off <= self.config.short_bpm_ratio:
                        candidates.append((off, k, j))
        for _, k, j in sorted(candidates):
            if not self.short(pieces, j):
                # the start or end of the neighbour's tempo that came out a bit off, the neighbour
                # keeps its grid. a tempo that drifts gives a row of short pieces with no long one
                # to go into, and a row of joins would flatten it into one line that fits nothing
                self.absorb(pieces, k, j, None)
                return True
            # two short pieces only join while the result is still short, then it goes into a long one
            lo = min(k, j)
            joined = pieces[:lo] + [self.piece(pieces[lo].first, pieces[lo + 1].stop)] + pieces[lo + 2:]
            if self.short(joined, lo):
                self.join(pieces, lo)
                return True
        return False

    def same_grid(self, pieces: list[_Piece]) -> bool:
        # the boundary test from the merge pass, on the beats each side fitted with indices
        # from the grid, since folded-in sections have spoilt the rough ones
        for k in range(len(pieces) - 1):
            a, b = pieces[k], pieces[k + 1]
            # grid-rounded indices make any neighbour look like the same tempo, so only near-equal
            # tempos get this far. anything further apart is the ratio check's or stays split
            if abs(b.fit.bpm / a.fit.bpm - 1.0) > self.config.bpm_shift_ratio:
                continue
            keep = np.concatenate((_kept(a.first, a.stop, a.excluded), _kept(b.first, b.stop, b.excluded)))
            t = self.times[a.first:b.stop][keep]
            j = int(_kept(a.first, a.stop, a.excluded).sum())
            if j < 2 or len(t) - j < 2:
                continue
            x = np.round((t - a.fit.offset_ms) / a.fit.period_ms)
            if np.any(np.diff(x) <= 0):
                continue
            if not _judge(x, t, j, self.config).justified:
                self.join(pieces, k)
                return True
        return False

    def run(self, ranges: list[tuple[int, int]], fits: list[GridFit]) -> list[_Piece]:
        pieces = [_Piece(a, b, fit) for (a, b), fit in zip(ranges, fits)]
        # each step changes the neighbours of the next, so go round until nothing moves
        for _ in range(4 * len(pieces)):
            steps = (
                self.same_grid,
                self.ratio_merge,
                self.edge_fold,
                self.short_run,
                self.weak_edge,
                self.short_merge,
            )
            if not any(step(pieces) for step in steps):
                break
        return pieces


# the ratios where the tracker took a different pulse rather than the same one an octave off
_FELT_RATIOS = tuple(r for r in RATIOS if r not in (Fraction(1, 2), Fraction(2, 1)))


def felt_sections(bpms: list[float], tolerance: float) -> list[bool]:
    """Which of these neighbouring segments sit between two others at a dotted or triplet ratio of both.

    bpms are the segments' fitted tempos in order. The octave check is careful with these:
    halving or doubling one can push it off every ratio the ratio check knows (3/4 halved is
    3/8), and then it can't be folded back in.
    """
    felt = [False] * len(bpms)
    for k in range(1, len(bpms) - 1):
        felt[k] = all(
            any(abs(bpms[k] / bpms[j] / float(r) - 1.0) <= tolerance for r in _FELT_RATIOS) for j in (k - 1, k + 1)
        )
    return felt


def related(bpm: float, other: float, tolerance: float) -> bool:
    """bpm is other's tempo, or one of the ratios a felt section can have to it."""
    return any(abs(bpm / other / float(r) - 1.0) <= tolerance for r in (Fraction(1), *RATIOS))


def build_tempo_map(
    times_ms: np.ndarray,
    is_downbeat: np.ndarray,
    start_ms: float,
    end_ms: float,
    downbeats_known: bool = True,
    config: TempoMapConfig = TempoMapConfig(),
    loudness: Callable[[float, float], float] | None = None,
    consolidate: bool = True,
) -> TempoMapResult:
    """Segments over [start_ms, end_ms], usually the trim points, with one fit per segment.

    loudness(start_ms, end_ms) gives a stretch's median level in db against the whole song,
    for the weak edge rule. consolidate=False stops after segmentation, with felt tempos and
    short edges still split, which is what the octave check wants to look at.
    """
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

    if consolidate:
        pieces = _Consolidator(times, downbeats, start_ms, end_ms, downbeats_known, config, loudness).run(ranges, fits)
    else:
        pieces = [_Piece(a, b, fit) for (a, b), fit in zip(ranges, fits)]

    segments: list[SegmentFit] = []
    for k, p in enumerate(pieces):
        fit = p.fit
        # a later segment starts on its own grid at its first beat, where a chart would put the bpm change
        seg_start = start_ms if k == 0 else fit.offset_ms + fit.period_ms * float(fit.indices[0])
        segments.append(SegmentFit(p.first, p.stop, seg_start, end_ms, fit, tuple(p.merges)))
    for k in range(len(segments) - 1):
        segments[k] = replace(segments[k], end_ms=segments[k + 1].start_ms)

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
