"""Bar lines from the tempo map and the meter map.

One rule, and the frontend draws with the same one (frontend/src/tempoMap.ts):

- Each tempo segment owns the time from a quarter of its period before its start up to
  the same point before the next segment, so a bpm change on a beat gives one line there.
- Inside a tempo segment, a meter segment that starts with it (within that quarter period)
  counts bars from the tempo segment's anchor. One that starts later starts a bar right
  there, snapped to the tempo grid, and counts from that line.
- A bar is numerator * 4 / denominator beats of the tempo segment's grid, so a span set to
  half the bpm has bars twice as long.
- Where there's no meter segment at all, bars are 4/4 from the anchor, which is how
  everything before milestone 4 was drawn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, Sequence

# same as tempo_edit.EDGE_FRACTION and the frontend's, a line this close before a boundary belongs after it
EDGE_FRACTION = 0.25
DEFAULT_NUMERATOR = 4
DEFAULT_DENOMINATOR = 4


class TempoLike(Protocol):
    start_ms: float
    end_ms: float
    bpm: float
    anchor_ms: float


class MeterLike(Protocol):
    start_ms: float
    end_ms: float
    numerator: int
    denominator: int


@dataclass(frozen=True)
class _Meter:
    start_ms: float
    end_ms: float
    numerator: int
    denominator: int


@dataclass(frozen=True)
class BarRegion:
    """A stretch with one tempo and one meter, and where its bars are counted from."""

    tempo: int
    # index into the meter map, -1 where there's no meter segment
    meter: int
    # lines from here (inclusive) to stop (exclusive) belong to this region
    from_ms: float
    stop_ms: float
    ref_ms: float
    bar_ms: float
    period_ms: float


def period_ms(bpm: float) -> float:
    return 60000.0 / bpm


def bar_beats(numerator: int, denominator: int) -> float:
    return numerator * 4.0 / denominator


def _snap(seg: TempoLike, time_ms: float) -> float:
    p = period_ms(seg.bpm)
    return seg.anchor_ms + round((time_ms - seg.anchor_ms) / p) * p


def regions(tempo_map: Sequence[TempoLike], meter_map: Sequence[MeterLike]) -> list[BarRegion]:
    meters: list[_Meter] = [_Meter(m.start_ms, m.end_ms, m.numerator, m.denominator) for m in meter_map]
    out: list[BarRegion] = []
    for i, seg in enumerate(tempo_map):
        p = period_ms(seg.bpm)
        lo = -math.inf if i == 0 else seg.start_ms - EDGE_FRACTION * p
        nxt = tempo_map[i + 1] if i + 1 < len(tempo_map) else None
        hi = math.inf if nxt is None else nxt.start_ms - EDGE_FRACTION * period_ms(nxt.bpm)
        edge = EDGE_FRACTION * p
        inside = [(j, m) for j, m in enumerate(meters) if m.end_ms > seg.start_ms + edge and m.start_ms < seg.end_ms - edge]
        default = bar_beats(DEFAULT_NUMERATOR, DEFAULT_DENOMINATOR) * p
        if not inside or inside[0][1].start_ms > seg.start_ms + edge:
            # no meter here, or a meter map that doesn't reach this far: 4/4 from the anchor
            stop = hi if not inside else _snap(seg, inside[0][1].start_ms) - edge
            out.append(BarRegion(i, -1, lo, stop, seg.anchor_ms, default, p))
        for k, (j, m) in enumerate(inside):
            starts_with_segment = m.start_ms <= seg.start_ms + edge
            ref = seg.anchor_ms if starts_with_segment else _snap(seg, m.start_ms)
            r_lo = lo if starts_with_segment else ref - edge
            r_hi = _snap(seg, inside[k + 1][1].start_ms) - edge if k + 1 < len(inside) else hi
            out.append(BarRegion(i, j, r_lo, r_hi, ref, bar_beats(m.numerator, m.denominator) * p, p))
    return out


def bar_lines(
    tempo_map: Sequence[TempoLike],
    meter_map: Sequence[MeterLike] = (),
    from_ms: float | None = None,
    to_ms: float | None = None,
) -> list[float]:
    """Every bar line in [from_ms, to_ms), by default from the first sound to the end of the tempo map."""
    if not tempo_map:
        return []
    first = tempo_map[0]
    if from_ms is None:
        from_ms = first.start_ms - EDGE_FRACTION * period_ms(first.bpm)
    if to_ms is None:
        to_ms = tempo_map[-1].end_ms
    lines: list[float] = []
    for r in regions(tempo_map, meter_map):
        lo, hi = max(r.from_ms, from_ms), min(r.stop_ms, to_ms)
        if hi <= lo:
            continue
        # tiny slack so a line sitting exactly on lo isn't lost to float noise
        k = math.ceil((lo - r.ref_ms) / r.bar_ms - 1e-9)
        while True:
            t = r.ref_ms + k * r.bar_ms
            if t >= hi:
                break
            lines.append(t)
            k += 1
    return lines


def bar_count(lines: Sequence[float], start_ms: float, end_ms: float, tolerance_ms: float = 0.5) -> int:
    """Bar lines in [start_ms, end_ms), the line on start_ms counted and the one on end_ms not."""
    return sum(1 for t in lines if start_ms - tolerance_ms <= t < end_ms - tolerance_ms)


def nearest_bar_line(lines: Sequence[float], time_ms: float) -> float | None:
    if not lines:
        return None
    return min(lines, key=lambda t: abs(t - time_ms))


def beat_lines(tempo_map: Sequence[TempoLike], from_ms: float | None = None, to_ms: float | None = None) -> list[float]:
    """Every grid line, each tempo segment's own from its anchor, with the same edge rule as the bars."""
    if not tempo_map:
        return []
    first = tempo_map[0]
    if from_ms is None:
        from_ms = first.start_ms - EDGE_FRACTION * period_ms(first.bpm)
    if to_ms is None:
        to_ms = tempo_map[-1].end_ms
    lines: list[float] = []
    for i, seg in enumerate(tempo_map):
        p = period_ms(seg.bpm)
        lo = -math.inf if i == 0 else seg.start_ms - EDGE_FRACTION * p
        nxt = tempo_map[i + 1] if i + 1 < len(tempo_map) else None
        hi = math.inf if nxt is None else nxt.start_ms - EDGE_FRACTION * period_ms(nxt.bpm)
        lo, hi = max(lo, from_ms), min(hi, to_ms)
        k = math.ceil((lo - seg.anchor_ms) / p - 1e-9)
        while seg.anchor_ms + k * p < hi:
            lines.append(seg.anchor_ms + k * p)
            k += 1
    return lines
