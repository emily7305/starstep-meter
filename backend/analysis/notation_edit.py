"""Applying and dismissing notation suggestions, and keeping those decisions through re-analysis.

Applying one is a single edit that keeps every grid line where it was. Half and double split
the tempo segment at both edges of the span, which sit on bar lines, without refitting
anything, and set the span to half or twice the bpm from the same line. Half keeps every
other line, double adds one between each pair. A fold puts the stretch on its neighbour's
grid, like match.
"""

from __future__ import annotations

from backend.analysis.bars import period_ms
from backend.analysis.tempo_edit import _notes_within
from backend.schema.models import NotationSuggestion, TempoSegment

# a span edge this close to a segment edge is that edge
EDGE_MS = 1.0
# the segment the suggestion was made on still has its bpm, near enough
SAME_BPM = 1e-4
# a fresh suggestion that covers more than this of a decided one of the same kind is that one again
SAME_SPAN = 0.5


class SuggestionError(ValueError):
    pass


def _ms(value: float) -> float:
    return round(float(value), 3)


def _line(seg: TempoSegment, time_ms: float) -> float:
    p = period_ms(seg.bpm)
    return _ms(seg.anchor_ms + round((time_ms - seg.anchor_ms) / p) * p)


def _same_bpm(a: float, b: float) -> bool:
    return abs(a / b - 1.0) <= SAME_BPM


def _apply_feel(tempo: list[TempoSegment], s: NotationSuggestion) -> list[TempoSegment]:
    index = next((i for i, t in enumerate(tempo) if t.start_ms - EDGE_MS <= s.start_ms and s.end_ms <= t.end_ms + EDGE_MS), None)
    if index is None:
        raise SuggestionError("the span isn't inside one tempo segment any more, re-analyze to get fresh suggestions")
    seg = tempo[index]
    if not _same_bpm(seg.bpm, s.grid_bpm):
        raise SuggestionError(f"the tempo there is {seg.bpm} bpm now, the suggestion was made on {s.grid_bpm}")
    factor = 0.5 if s.kind == "half" else 2.0
    start = seg.start_ms if s.start_ms - seg.start_ms <= EDGE_MS else _ms(s.start_ms)
    end = seg.end_ms if seg.end_ms - s.end_ms <= EDGE_MS else _ms(s.end_ms)
    p = period_ms(seg.bpm)
    out: list[TempoSegment] = []
    if start > seg.start_ms:
        out.append(seg.model_copy(update={
            "end_ms": start, "source": "manual", "ratio_merged": _notes_within(seg.ratio_merged, seg.start_ms, start, p),
        }))
    # the span's anchor is the old line on its first bar line, at seg.bpm * factor its lines are
    # every other old line (half) or the old lines and the halves between them (double)
    out.append(seg.model_copy(update={
        "start_ms": start,
        "end_ms": end,
        "bpm": seg.bpm * factor,
        "anchor_ms": seg.anchor_ms if start == seg.start_ms else _line(seg, start),
        "confidence": None,
        "source": "manual",
        "ratio_merged": _notes_within(seg.ratio_merged, start, end, p),
    }))
    if end < seg.end_ms:
        out.append(seg.model_copy(update={
            "start_ms": end,
            "anchor_ms": _line(seg, end),
            "source": "manual",
            "ratio_merged": _notes_within(seg.ratio_merged, end, seg.end_ms, p),
        }))
    return [*tempo[:index], *out, *tempo[index + 1:]]


def _apply_fold(tempo: list[TempoSegment], s: NotationSuggestion) -> list[TempoSegment]:
    run = [i for i, t in enumerate(tempo) if t.end_ms > s.start_ms + EDGE_MS and t.start_ms < s.end_ms - EDGE_MS]
    if not run or len(run) == len(tempo):
        raise SuggestionError("there's no neighbour to fold this stretch into")
    lo, hi = run[0], run[-1]
    if abs(tempo[lo].start_ms - s.start_ms) > EDGE_MS or abs(tempo[hi].end_ms - s.end_ms) > EDGE_MS:
        raise SuggestionError("the tempo map changed there, re-analyze to get fresh suggestions")
    if not _same_bpm(tempo[lo].bpm, s.grid_bpm):
        raise SuggestionError(f"the tempo there is {tempo[lo].bpm} bpm now, the suggestion was made on {s.grid_bpm}")
    # the stretch is at one end of the song, its neighbour is on the other side
    other = hi + 1 if lo == 0 and hi + 1 < len(tempo) else lo - 1
    if other < 0:
        raise SuggestionError("there's no neighbour to fold this stretch into")
    a, b = min(other, lo), max(other, hi)
    notes = [n for t in tempo[a:b + 1] for n in t.ratio_merged]
    folded = tempo[other].model_copy(update={
        "start_ms": tempo[a].start_ms, "end_ms": tempo[b].end_ms, "confidence": None, "source": "manual", "ratio_merged": notes,
    })
    return [*tempo[:a], folded, *tempo[b + 1:]]


def apply_suggestion(tempo: list[TempoSegment], suggestions: list[NotationSuggestion], index: int) -> list[TempoSegment]:
    """The tempo map with suggestion index applied. The caller marks it applied."""
    if not 0 <= index < len(suggestions):
        raise SuggestionError(f"no suggestion {index}, there are {len(suggestions)}")
    s = suggestions[index]
    if s.status != "open":
        raise SuggestionError(f"suggestion {index} was already {s.status}")
    return _apply_fold(tempo, s) if s.kind == "fold" else _apply_feel(tempo, s)


def _overlap(a: NotationSuggestion, b: NotationSuggestion) -> float:
    shared = min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms)
    return max(0.0, shared) / max(min(a.end_ms - a.start_ms, b.end_ms - b.start_ms), 1e-9)


def keep_decided(
    previous: list[NotationSuggestion], fresh: list[NotationSuggestion], tempo: list[TempoSegment]
) -> list[NotationSuggestion]:
    """Fresh suggestions plus every applied or dismissed one from before, which stay as they were.

    A fresh one goes when it's a decided one again (same kind, mostly the same span), or when
    a manual tempo segment over it has another bpm than the one it was made on, the user has
    already retimed that stretch.
    """
    decided = [s for s in previous if s.status != "open"]
    out = list(decided)
    for f in fresh:
        if any(d.kind == f.kind and _overlap(d, f) > SAME_SPAN for d in decided):
            continue
        retimed = any(
            t.source == "manual" and t.end_ms > f.start_ms and t.start_ms < f.end_ms and not _same_bpm(t.bpm, f.grid_bpm)
            for t in tempo
        )
        if not retimed:
            out.append(f)
    return sorted(out, key=lambda s: (s.start_ms, s.kind))
