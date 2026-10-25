"""Confidence per tempo segment and per stretch of one, from the fit residuals and the cross-check.

Two things say the grid may be wrong somewhere:

- residual share: the share of tracked beats within tolerance_ms of their grid line (or of the
  subdivision a felt beat sits on), what the segment confidence was up to milestone 5
- agreement: the share of compared beats where librosa's tracker had a beat within the
  cross-check's max_disagreement_ms (cross_check.py)

confidence = residual_share * (1 - agreement_weight + agreement_weight * agreement)

So a stretch where both trackers fully disagree keeps half of its residual share, librosa is the
weaker tracker and can be the one that's wrong. Without a cross-check it's the residual share.

Misfits the analysis expects don't count against it:

- a felt section's beats follow another pulse and madmom fills its gaps with guesses, so each beat
  in one counts as min(1, fit) of its section, how well the grid caught the section against how
  well its own tempo did. the cross-check skips felt sections
- an off-beat run, and the beats ramping into and out of it, are left out. the grid is on the
  real beats there, the tracker followed the off-beat. the cross-check skips them too

Spans are window_beats long on each segment's grid, counted from its anchor, so in 4/4 they're
four bars and start on a bar line. The formula and the numbers are in docs/decisions.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from backend.analysis.cross_check import CrossCheck
from backend.analysis.grid_fit import CONFIDENCE_TOLERANCE_MS, NO_DOWNBEAT_CONFIDENCE_SCALE
from backend.analysis.tempo_map import SegmentFit, TempoMapResult


@dataclass(frozen=True)
class ConfidenceConfig:
    # four bars of 4/4, the same stretch the tempo map smooths its residuals over
    window_beats: int = 16
    tolerance_ms: float = CONFIDENCE_TOLERANCE_MS
    agreement_weight: float = 0.5
    # a span under this is shaded on the timeline. on the three real songs the next lowest after
    # the fades, a late intro and a lost beat is 0.56. tuned on those, revisit
    low: float = 0.5
    # beats either side of an off-beat run that ramp between the line and the half line. the
    # ramps on the real songs are 3 to 7 beats
    ramp_max_beats: int = 8

    def __post_init__(self) -> None:
        if self.window_beats < 4 or not self.tolerance_ms > 0:
            raise ValueError("confidence window and tolerance are out of range")
        if not 0 <= self.agreement_weight <= 1 or not 0 <= self.low <= 1 or self.ramp_max_beats < 0:
            raise ValueError("confidence weights are out of range")


@dataclass(frozen=True)
class Span:
    start_ms: float
    end_ms: float
    confidence: float
    # None where every beat was left out, the span then takes its segment's share
    residual_share: float | None
    # None without a cross-check, or with no compared beat in the span
    agreement: float | None
    low: bool


@dataclass(frozen=True)
class Confidence:
    # one per tempo segment
    segments: list[float]
    spans: list[Span]


def _combine(share: float, agreement: float | None, weight: float) -> float:
    if agreement is None:
        return share
    return share * (1.0 - weight + weight * agreement)


def _ramp(residuals: np.ndarray, start: int, step: int, lo: int, hi: int, config: ConfidenceConfig) -> int:
    # walks away from the run while the beats sit off both the line and the half line
    i, n = start, 0
    while lo <= i + step < hi and n < config.ramp_max_beats and abs(residuals[i + step]) > config.tolerance_ms:
        i += step
        n += 1
    return i


def expected_misfits(
    tempo: TempoMapResult, times_ms: np.ndarray, config: ConfidenceConfig = ConfidenceConfig()
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float]]]:
    """The felt sections as (start, end, fit) and the off-beat runs with their ramps as (start, end), in ms."""
    times = np.asarray(times_ms, dtype=np.float64)
    felt = [(m.start_ms, m.end_ms, m.fit) for s in tempo.segments for m in s.ratio_merges]
    offbeat: list[tuple[float, float]] = []
    for s in tempo.segments:
        for run in s.offbeat_runs:
            first = int(np.searchsorted(times, run.start_ms - 1e-6))
            last = int(np.searchsorted(times, run.end_ms + 1e-6)) - 1
            first = _ramp(tempo.residuals_ms, first, -1, s.first, s.stop, config)
            last = _ramp(tempo.residuals_ms, last, 1, s.first, s.stop, config)
            offbeat.append((float(times[first]), float(times[last])))
    return felt, offbeat


def beat_scores(
    tempo: TempoMapResult,
    times_ms: np.ndarray,
    felt: list[tuple[float, float, float]],
    offbeat: list[tuple[float, float]],
    config: ConfidenceConfig = ConfidenceConfig(),
) -> np.ndarray:
    """1 for a beat on the grid, 0 off it, min(1, fit) in a felt section, nan where it's left out."""
    times = np.asarray(times_ms, dtype=np.float64)
    scores = (np.abs(tempo.residuals_ms) <= config.tolerance_ms).astype(np.float64)
    for a, b, fit in felt:
        scores[(times >= a) & (times <= b)] = min(1.0, fit)
    for a, b in offbeat:
        scores[(times >= a) & (times <= b)] = np.nan
    return scores


def window_edges(seg: SegmentFit, window_beats: int) -> list[float]:
    """Span edges over the segment, every window_beats grid lines from its anchor, no stub under half a window."""
    width = window_beats * seg.fit.period_ms
    k = math.floor((seg.start_ms - seg.anchor_ms) / width) + 1
    edges = [seg.start_ms]
    while seg.anchor_ms + k * width < seg.end_ms:
        edges.append(seg.anchor_ms + k * width)
        k += 1
    edges.append(seg.end_ms)
    if len(edges) > 2 and edges[1] - edges[0] < width / 2:
        del edges[1]
    if len(edges) > 2 and edges[-1] - edges[-2] < width / 2:
        del edges[-2]
    return edges


def _mean(values: np.ndarray) -> float | None:
    values = values[~np.isnan(values)]
    return float(np.mean(values)) if len(values) else None


def _agreement(cross: CrossCheck | None, start: float, end: float) -> float | None:
    if cross is None:
        return None
    inside = (cross.times_ms >= start) & (cross.times_ms < end)
    return float(np.mean(cross.agrees[inside])) if inside.any() else None


def assess(
    tempo: TempoMapResult,
    times_ms: np.ndarray,
    cross: CrossCheck | None = None,
    config: ConfidenceConfig = ConfidenceConfig(),
) -> Confidence:
    """Segment confidences and the spans, on the tempo map's own beats (the snapped ones)."""
    times = np.asarray(times_ms, dtype=np.float64)
    felt, offbeat = expected_misfits(tempo, times, config)
    scores = beat_scores(tempo, times, felt, offbeat, config)
    segments: list[float] = []
    spans: list[Span] = []
    for s in tempo.segments:
        own_times, own_scores = times[s.first:s.stop], scores[s.first:s.stop]
        share = _mean(own_scores)
        seg_share = 1.0 if share is None else share
        conf = _combine(seg_share, _agreement(cross, s.start_ms, s.end_ms), config.agreement_weight)
        # librosa has no downbeats, the bar phase is a guess. that's the segment's number, the spans
        # are about where the grid sits and stay as they are
        segments.append(conf if tempo.downbeats_known else conf * NO_DOWNBEAT_CONFIDENCE_SCALE)
        edges = window_edges(s, config.window_beats)
        for a, b in zip(edges, edges[1:]):
            last = b == edges[-1]
            inside = (own_times >= a) & ((own_times <= b) if last else (own_times < b))
            span_share = _mean(own_scores[inside])
            agreement = _agreement(cross, a, b)
            value = _combine(seg_share if span_share is None else span_share, agreement, config.agreement_weight)
            spans.append(Span(a, b, value, span_share, agreement, value < config.low))
    return Confidence(segments, spans)
