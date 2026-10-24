"""Manual tempo map edits, and keeping them through re-analysis.

Plain functions on lists of TempoSegment, each returns a new list and never
touches the one it got. The api applies them and writes the edit log.

Two things say what a segment is. source "manual" means the user touched it,
its boundaries or its values, so re-analysis leaves it alone. confidence
null means its bpm and anchor were set by hand. A segment that still has a
confidence was fitted, so split and merge can fit it again from the tracked
beats instead of carrying a tempo that only made sense for the old extent.

A segment's ratio_merged sections are felt tempo stretches the analysis kept
on its grid. They're left out of every refit, the way the analysis left them
out, and they follow the segment through splits and merges. Splitting at a
section's start and end gives it back as its own segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from backend.analysis.grid_fit import MIN_BEATS, GridFitError, fit_grid
from backend.schema.models import RatioMergedSection, TempoSegment

# a split this close to a segment edge, in beats of that segment, makes a sliver nobody meant
MIN_SPLIT_BEATS = 0.5
# a beat within this fraction of a period before a boundary already belongs to the next segment,
# same rule the ui uses for drawing
EDGE_FRACTION = 0.25
# a ratio merged section within this of both its segment's edges is the segment itself
SAME_EDGE_MS = 1.0


class TempoEditError(ValueError):
    pass


@dataclass(frozen=True)
class TrackedTimes:
    """What split and merge refit from, read from the beats file."""

    times_ms: np.ndarray
    is_downbeat: np.ndarray
    downbeats_known: bool


def _ms(value: float) -> float:
    return round(float(value), 3)


def period_ms(segment: TempoSegment) -> float:
    return 60000.0 / segment.bpm


def _check_index(segments: list[TempoSegment], index: int) -> None:
    if not 0 <= index < len(segments):
        raise TempoEditError(f"no tempo segment {index}, there are {len(segments)}")


def _manual(segment: TempoSegment, **changes: object) -> TempoSegment:
    return segment.model_copy(update={"source": "manual", **changes})


def set_bpm(segments: list[TempoSegment], index: int, bpm: float) -> list[TempoSegment]:
    # the anchor stays put and the grid is rebuilt around it, that's what x2 and /2 rely on
    _check_index(segments, index)
    out = list(segments)
    out[index] = _manual(segments[index], bpm=bpm, confidence=None)
    return out


def set_anchor(segments: list[TempoSegment], index: int, anchor_ms: float) -> list[TempoSegment]:
    _check_index(segments, index)
    seg = segments[index]
    # anywhere inside the segment, plus a beat of slack so nudging an anchor that sits on an edge still works
    slack = period_ms(seg)
    if not seg.start_ms - slack <= anchor_ms <= seg.end_ms + slack:
        raise TempoEditError(f"anchor_ms has to be inside segment {index} ({seg.start_ms} to {seg.end_ms} ms)")
    out = list(segments)
    out[index] = _manual(seg, anchor_ms=anchor_ms, confidence=None)
    return out


def _notes_within(notes: list[RatioMergedSection], start_ms: float, end_ms: float, period: float) -> list[RatioMergedSection]:
    # the sections clipped to [start, end). one that covers all of it is the segment now, and a
    # clipped piece shorter than a beat isn't a section anymore
    out = []
    for note in notes:
        a, b = max(note.start_ms, start_ms), min(note.end_ms, end_ms)
        if b - a < period or (a - start_ms <= SAME_EDGE_MS and end_ms - b <= SAME_EDGE_MS):
            continue
        out.append(note if (a, b) == (note.start_ms, note.end_ms) else note.model_copy(update={"start_ms": a, "end_ms": b}))
    return out


def _beats_in(
    tracked: TrackedTimes, start_ms: float, end_ms: float, period: float, skip: list[RatioMergedSection] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    edge = EDGE_FRACTION * period
    keep = (tracked.times_ms >= start_ms - edge) & (tracked.times_ms < end_ms - edge)
    for note in skip or []:
        keep &= ~((tracked.times_ms >= note.start_ms - edge) & (tracked.times_ms < note.end_ms - edge))
    return tracked.times_ms[keep], tracked.is_downbeat[keep]


def _refit(seg: TempoSegment, tracked: TrackedTimes | None) -> TempoSegment | None:
    # a fresh fit over the segment's own beats, None when there's too little to fit. the
    # ratio merged sections are another pulse, they'd pull the fit off the notated one
    if tracked is None:
        return None
    times, downbeats = _beats_in(tracked, seg.start_ms, seg.end_ms, period_ms(seg), seg.ratio_merged)
    if len(times) < MIN_BEATS:
        return None
    try:
        fit = fit_grid(times, downbeats, downbeats_known=tracked.downbeats_known)
    except GridFitError:
        return None
    return seg.model_copy(update={"bpm": round(fit.bpm, 4), "anchor_ms": _ms(fit.offset_ms), "confidence": round(fit.confidence, 3)})


def _grid_line_at_or_after(seg: TempoSegment, time_ms: float) -> float:
    period = period_ms(seg)
    k = np.ceil((time_ms - seg.anchor_ms) / period - 1e-9)
    return _ms(seg.anchor_ms + k * period)


def split(segments: list[TempoSegment], at_ms: float, tracked: TrackedTimes | None = None) -> list[TempoSegment]:
    """Split the segment that contains at_ms into two manual segments, the boundary at at_ms.

    A fitted segment gets each side refit from the tracked beats in it. A hand-set one, or a
    side with too few beats, keeps the old grid, and the right side's anchor moves to the first
    grid line from the split on, so the grid doesn't move and the new bar starts there.
    """
    index = next((i for i, s in enumerate(segments) if s.start_ms < at_ms < s.end_ms), None)
    if index is None:
        raise TempoEditError(f"{at_ms} ms isn't inside any tempo segment")
    seg = segments[index]
    gap = MIN_SPLIT_BEATS * period_ms(seg)
    if at_ms - seg.start_ms < gap or seg.end_ms - at_ms < gap:
        raise TempoEditError("a split has to be at least half a beat away from the segment's edges")

    at = _ms(at_ms)
    period = period_ms(seg)
    left = _manual(seg, end_ms=at, ratio_merged=_notes_within(seg.ratio_merged, seg.start_ms, at, period))
    right = _manual(
        seg,
        start_ms=at,
        anchor_ms=_grid_line_at_or_after(seg, at),
        ratio_merged=_notes_within(seg.ratio_merged, at, seg.end_ms, period),
    )
    if right.anchor_ms >= right.end_ms:
        right = right.model_copy(update={"anchor_ms": at})
    if seg.confidence is not None:
        left = _refit(left, tracked) or left.model_copy(update={"confidence": None})
        right = _refit(right, tracked) or right.model_copy(update={"confidence": None})
    return [*segments[:index], left, right, *segments[index + 1:]]


def merge(segments: list[TempoSegment], index: int, tracked: TrackedTimes | None = None) -> list[TempoSegment]:
    """Merge segment index with the one after it into one manual segment.

    Two fitted segments are refit as one from the tracked beats. If one of them was set by
    hand its grid wins, and if both were, the first one's does.
    """
    _check_index(segments, index)
    if index + 1 >= len(segments):
        raise TempoEditError(f"segment {index} is the last one, there's nothing after it to merge with")
    first, second = segments[index], segments[index + 1]
    keeps = second if first.confidence is not None and second.confidence is None else first
    notes = [*first.ratio_merged, *second.ratio_merged]
    merged = _manual(keeps, start_ms=first.start_ms, end_ms=second.end_ms, ratio_merged=notes)
    if first.confidence is not None and second.confidence is not None:
        merged = _refit(merged, tracked) or merged.model_copy(update={"confidence": None})
    return [*segments[:index], merged, *segments[index + 2:]]


def match(segments: list[TempoSegment], index: int, side: Literal["previous", "next"]) -> list[TempoSegment]:
    """Segment index takes the grid of the segment before or after it and becomes part of it.

    For a stretch that is the neighbour's tempo felt differently, or that the analysis got a
    little off. The neighbour's bpm and anchor carry over as they are, nothing is refit, and
    the result is one manual segment with no confidence since its extent was set by hand.
    """
    _check_index(segments, index)
    other = index - 1 if side == "previous" else index + 1
    if not 0 <= other < len(segments):
        raise TempoEditError(f"segment {index} has no {side} segment to match")
    lo, hi = min(index, other), max(index, other)
    notes = [*segments[lo].ratio_merged, *segments[hi].ratio_merged]
    matched = _manual(
        segments[other],
        start_ms=segments[lo].start_ms,
        end_ms=segments[hi].end_ms,
        confidence=None,
        ratio_merged=notes,
    )
    return [*segments[:lo], matched, *segments[hi + 1:]]


def _pieces(fresh: list[TempoSegment], start_ms: float, end_ms: float) -> list[TempoSegment]:
    # the fresh auto segments clipped to [start, end), stretched to reach both ends
    inside = [s for s in fresh if s.end_ms > start_ms and s.start_ms < end_ms]
    if not inside:
        # the gap is outside what the new analysis covers, the nearest fresh segment fills it
        inside = [fresh[0] if end_ms <= fresh[0].start_ms else fresh[-1]]
    pieces = [s.model_copy(update={"start_ms": max(s.start_ms, start_ms), "end_ms": min(s.end_ms, end_ms)}) for s in inside]
    pieces[0] = pieces[0].model_copy(update={"start_ms": start_ms})
    pieces[-1] = pieces[-1].model_copy(update={"end_ms": end_ms})
    return [
        p.model_copy(update={"ratio_merged": _notes_within(p.ratio_merged, p.start_ms, p.end_ms, period_ms(p))})
        for p in pieces
    ]


def keep_manual_segments(previous: list[TempoSegment], fresh: list[TempoSegment]) -> list[TempoSegment]:
    """The fresh auto map with every manual segment from before put back, untouched.

    Auto segments only fill the time the manual ones don't cover, clipped at their edges.
    """
    manual = sorted((s for s in previous if s.source == "manual"), key=lambda s: s.start_ms)
    if not manual or not fresh:
        return list(fresh) if fresh else list(manual)
    out: list[TempoSegment] = []
    cursor = min(fresh[0].start_ms, manual[0].start_ms)
    for seg in manual:
        if seg.start_ms > cursor:
            out.extend(_pieces(fresh, cursor, seg.start_ms))
        out.append(seg)
        cursor = seg.end_ms
    end = max(fresh[-1].end_ms, manual[-1].end_ms)
    if end > cursor:
        out.extend(_pieces(fresh, cursor, end))
    return out
