"""Manual meter edits, and keeping them through re-analysis.

Plain functions on lists of MeterSegment, like tempo_edit. source "manual" means the user
touched the segment, its signature or its edges, so re-analysis leaves it alone. confidence
null means its signature was set by hand.
"""

from __future__ import annotations

from backend.analysis.bars import EDGE_FRACTION, period_ms
from backend.schema.models import MeterSegment, TempoSegment


class MeterEditError(ValueError):
    pass


def _ms(value: float) -> float:
    return round(float(value), 3)


def meter_or_default(meter: list[MeterSegment], tempo: list[TempoSegment]) -> list[MeterSegment]:
    """The meter map, or one 4/4 over the whole tempo map when there's none (a report from before 2.3)."""
    if meter or not tempo:
        return list(meter)
    return [MeterSegment(start_ms=tempo[0].start_ms, end_ms=tempo[-1].end_ms, numerator=4, denominator=4, source="auto")]


def _check_index(meter: list[MeterSegment], index: int) -> None:
    if not 0 <= index < len(meter):
        raise MeterEditError(f"no meter segment {index}, there are {len(meter)}")


def set_meter(meter: list[MeterSegment], index: int, numerator: int, denominator: int) -> list[MeterSegment]:
    _check_index(meter, index)
    out = list(meter)
    out[index] = meter[index].model_copy(
        update={"numerator": numerator, "denominator": denominator, "confidence": None, "source": "manual"}
    )
    return out


def _grid_line(tempo: list[TempoSegment], at_ms: float) -> float:
    # the beat nearest at_ms on the tempo segment that holds it, a meter change starts a bar on a beat
    seg = next((s for s in tempo if s.start_ms <= at_ms < s.end_ms), tempo[-1] if at_ms >= tempo[-1].end_ms else tempo[0])
    p = period_ms(seg.bpm)
    return _ms(seg.anchor_ms + round((at_ms - seg.anchor_ms) / p) * p)


def split_meter(meter: list[MeterSegment], tempo: list[TempoSegment], at_ms: float) -> list[MeterSegment]:
    """Split the meter segment at the beat nearest at_ms, both sides manual, bars restart there."""
    at = _grid_line(tempo, at_ms)
    index = next((i for i, m in enumerate(meter) if m.start_ms < at < m.end_ms), None)
    if index is None:
        raise MeterEditError(f"{at} ms isn't inside any meter segment")
    seg = meter[index]
    slack = EDGE_FRACTION * min(period_ms(t.bpm) for t in tempo)
    if at - seg.start_ms < slack or seg.end_ms - at < slack:
        raise MeterEditError("that's already where a meter segment starts")
    left = seg.model_copy(update={"end_ms": at, "source": "manual"})
    right = seg.model_copy(update={"start_ms": at, "source": "manual"})
    return [*meter[:index], left, right, *meter[index + 1:]]


def merge_meter(meter: list[MeterSegment], index: int) -> list[MeterSegment]:
    """Merge meter segment index with the one after it. A signature set by hand wins, the first one's if both were."""
    _check_index(meter, index)
    if index + 1 >= len(meter):
        raise MeterEditError(f"meter segment {index} is the last one, there's nothing after it to merge with")
    first, second = meter[index], meter[index + 1]
    keeps = second if first.confidence is not None and second.confidence is None else first
    merged = keeps.model_copy(update={"start_ms": first.start_ms, "end_ms": second.end_ms, "source": "manual"})
    return [*meter[:index], merged, *meter[index + 2:]]


def keep_manual_meter(previous: list[MeterSegment], fresh: list[MeterSegment]) -> list[MeterSegment]:
    """The fresh auto meter map with every manual segment from before put back, untouched."""
    manual = sorted((m for m in previous if m.source == "manual"), key=lambda m: m.start_ms)
    if not manual or not fresh:
        return list(fresh) if fresh else list(manual)

    def pieces(start: float, end: float) -> list[MeterSegment]:
        inside = [m for m in fresh if m.end_ms > start and m.start_ms < end]
        if not inside:
            inside = [fresh[0] if end <= fresh[0].start_ms else fresh[-1]]
        out = [m.model_copy(update={"start_ms": max(m.start_ms, start), "end_ms": min(m.end_ms, end)}) for m in inside]
        out[0] = out[0].model_copy(update={"start_ms": start})
        out[-1] = out[-1].model_copy(update={"end_ms": end})
        return out

    out: list[MeterSegment] = []
    cursor = min(fresh[0].start_ms, manual[0].start_ms)
    for seg in manual:
        if seg.start_ms > cursor:
            out.extend(pieces(cursor, seg.start_ms))
        out.append(seg)
        cursor = seg.end_ms
    end = max(fresh[-1].end_ms, manual[-1].end_ms)
    if end > cursor:
        out.extend(pieces(cursor, end))
    return out
