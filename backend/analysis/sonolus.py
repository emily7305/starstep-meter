"""The values a Sonolus level needs, from a tempo map and a meter map.

Sonolus' level data is {bgmOffset, entities} (LevelData in @sonolus/core). Tempo goes in
as #BPM_CHANGE entities with a #BEAT and a #BPM. Level time 0 is beat 0, and the bgm plays
at level time + bgmOffset seconds, which is how the official osu and TJA converters in
sonolus-taiko-engine write it. There's no time signature archetype, so those come out as a
separate list for the chart editor. See docs/decisions.md (Sonolus export) for the sources.

Every time here comes from the segment anchors, the first downbeat is tempo_map[0].anchor_ms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from backend.analysis.bars import (
    DEFAULT_DENOMINATOR,
    DEFAULT_NUMERATOR,
    EDGE_FRACTION,
    MeterLike,
    TempoLike,
    bar_beats,
    bar_starts,
    period_ms,
    regions,
)

BPM_CHANGE = "#BPM_CHANGE"
BEAT = "#BEAT"
BPM = "#BPM"

# beats are rounded to this many decimals, a millionth of a beat is under a microsecond at any bpm
BEAT_DECIMALS = 6
# a bar this close to its meter's length in beats is a full bar, anything else got cut short
FULL_BAR_BEATS = 1e-4
DENOMINATORS = (1, 2, 4, 8, 16, 32, 64)


class SonolusError(ValueError):
    pass


@dataclass(frozen=True)
class BpmChange:
    beat: float
    bpm: float
    # on the report's timeline, before decoder compensation
    time_ms: float


@dataclass(frozen=True)
class TimeSignature:
    beat: float
    numerator: int
    denominator: int


@dataclass(frozen=True)
class SonolusTiming:
    bgm_offset_s: float
    first_downbeat_beat: float
    bpm_changes: list[BpmChange]
    time_signatures: list[TimeSignature]


@dataclass(frozen=True)
class _Change:
    time_ms: float
    bpm: float
    beat: float

    @property
    def period_ms(self) -> float:
        return period_ms(self.bpm)


def decoder_padding_ms(padding_samples: int, sample_rate: int) -> float:
    return padding_samples / sample_rate * 1000.0


def _first_line(seg: TempoLike) -> float:
    # the segment's first grid line, with the same quarter period rule the bars use
    p = period_ms(seg.bpm)
    k = math.ceil((seg.start_ms - EDGE_FRACTION * p - seg.anchor_ms) / p - 1e-9)
    return seg.anchor_ms + k * p


def _line_cut(seg: TempoLike) -> float:
    return seg.start_ms - EDGE_FRACTION * period_ms(seg.bpm)


def _beat_zero(tempo_map: Sequence[TempoLike], meter_map: Sequence[MeterLike]) -> float:
    # the latest bar line of the first segment at or before the start of the audio, so beat 0 is
    # a bar line and nothing before the first downbeat (a pickup, the intro) is skipped
    first = regions(tempo_map, meter_map)[0]
    k = math.ceil(first.ref_ms / first.bar_ms - 1e-9)
    return first.ref_ms - k * first.bar_ms


def _changes(tempo_map: Sequence[TempoLike], start_ms: float) -> list[_Change]:
    out = [_Change(start_ms, tempo_map[0].bpm, 0.0)]
    for i in range(1, len(tempo_map)):
        seg = tempo_map[i]
        at = _first_line(seg)
        nxt = tempo_map[i + 1] if i + 1 < len(tempo_map) else None
        # a segment shorter than the quarter period edges has no line of its own, and a change
        # there would have to go back in time. nothing is on its grid, so the tempo before runs on
        if nxt is not None and at >= _line_cut(nxt):
            continue
        prev = out[-1]
        out.append(_Change(at, seg.bpm, prev.beat + (at - prev.time_ms) / prev.period_ms))
    return out


def _beat_at(changes: list[_Change], time_ms: float) -> float:
    change = changes[0]
    for c in changes:
        if c.time_ms <= time_ms + 1e-6:
            change = c
    return change.beat + (time_ms - change.time_ms) / change.period_ms


def _signature(length_beats: float, preferred_denominator: int) -> tuple[int, int]:
    # a cut bar written as n/d, the bar's own denominator first so half a 4/4 bar reads 2/4
    for d in (preferred_denominator, *DENOMINATORS):
        n = length_beats * d / 4
        if round(n) >= 1 and abs(round(n) * 4 / d - length_beats) < FULL_BAR_BEATS:
            return round(n), d
    # todo: a bar that isn't a whole number of 64ths only happens next to a bpm change on a
    # fractional beat. the next entry's beat is exact, so an editor that restarts there is right
    return max(1, round(length_beats * 16)), 64


def _time_signatures(
    tempo_map: Sequence[TempoLike], meter_map: Sequence[MeterLike], changes: list[_Change], start_ms: float
) -> list[TimeSignature]:
    starts = bar_starts(tempo_map, meter_map, from_ms=start_ms)
    beats = [_beat_at(changes, t) for t, _ in starts]
    out: list[TimeSignature] = []
    for j, (_, region) in enumerate(starts):
        meter = meter_map[region.meter] if region.meter >= 0 else None
        nominal = (meter.numerator, meter.denominator) if meter is not None else (DEFAULT_NUMERATOR, DEFAULT_DENOMINATOR)
        signature = nominal
        if j + 1 < len(beats):
            length = beats[j + 1] - beats[j]
            if abs(length - bar_beats(*nominal)) >= FULL_BAR_BEATS:
                signature = _signature(length, nominal[1])
        if not out or (out[-1].numerator, out[-1].denominator) != signature:
            out.append(TimeSignature(round(beats[j], BEAT_DECIMALS), *signature))
    return out


def sonolus_timing(
    tempo_map: Sequence[TempoLike], meter_map: Sequence[MeterLike] = (), decoder_compensation_ms: float = 0.0
) -> SonolusTiming:
    """bgmOffset, bpm changes and time signatures for a Sonolus level.

    decoder_compensation_ms is how much later than ffmpeg's timeline the player's decoder plays
    the audio, the source's decoder padding for a decoder that ignores gapless info. It only
    moves bgmOffset, every beat stays where it is.
    """
    if not tempo_map:
        raise SonolusError("the tempo map is empty")
    if not math.isfinite(decoder_compensation_ms):
        raise SonolusError("decoder compensation has to be a number of ms")
    start_ms = _beat_zero(tempo_map, meter_map)
    changes = _changes(tempo_map, start_ms)
    return SonolusTiming(
        # the bgm is at level time + bgmOffset, and level time 0 is beat 0. a positive value skips
        # only the decoder's padding, beat 0 is never after the start of the audio
        bgm_offset_s=round((start_ms + decoder_compensation_ms) / 1000.0, 6),
        first_downbeat_beat=round(_beat_at(changes, tempo_map[0].anchor_ms), BEAT_DECIMALS),
        bpm_changes=[BpmChange(round(c.beat, BEAT_DECIMALS), c.bpm, round(c.time_ms, 3)) for c in changes],
        time_signatures=_time_signatures(tempo_map, meter_map, changes, start_ms),
    )


def level_entities(timing: SonolusTiming) -> list[dict]:
    """The #BPM_CHANGE entities for LevelData.entities, in Sonolus' own shape."""
    return [
        {"archetype": BPM_CHANGE, "data": [{"name": BEAT, "value": c.beat}, {"name": BPM, "value": c.bpm}]}
        for c in timing.bpm_changes
    ]
