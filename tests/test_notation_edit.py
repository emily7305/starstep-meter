"""Applying and dismissing suggestions, manual meter, and both through re-analysis."""

import numpy as np
import pytest

from backend.analysis.bars import bar_count, bar_lines, beat_lines
from backend.analysis.meter_edit import MeterEditError, keep_manual_meter, merge_meter, set_meter, split_meter
from backend.analysis.notation_edit import SuggestionError, apply_suggestion, keep_decided
from backend.schema.models import MeterSegment, NotationSuggestion, RatioMergedSection, TempoSegment

# real_b's grid, 4 decimals as the report has it
BPM = 259.9963
ANCHOR = 97.229
PERIOD = 60000.0 / BPM
END = 176448.979


def _tempo(start=ANCHOR, end=END, bpm=BPM, anchor=ANCHOR, source="auto", confidence=0.886):
    return TempoSegment(start_ms=start, end_ms=end, bpm=bpm, anchor_ms=anchor, confidence=confidence, source=source)


def _bar(k):
    # bar lines of 4/4 at the grid, the k-th from the anchor
    return round(ANCHOR + 4 * k * PERIOD, 3)


def _suggestion(kind, start, end, grid_bpm=BPM, status="open"):
    factor = {"half": 0.5, "double": 2.0, "fold": 1.0}[kind]
    return NotationSuggestion(
        start_ms=start, end_ms=end, kind=kind, suggested_bpm=round(grid_bpm * factor, 4), grid_bpm=grid_bpm, score=0.6, status=status
    )


def _near_any(lines, others, tol):
    others = np.asarray(others)
    return all(np.abs(others - t).min() <= tol for t in lines)


METER = [MeterSegment(start_ms=ANCHOR, end_ms=END, numerator=4, denominator=4, confidence=1.0, source="auto")]


# --- apply ---


def test_applying_half_keeps_every_grid_line_and_halves_the_bars():
    # 21 to 69 of the measure map written at 130 is grid bars 40 to 88 here, start them on bar lines
    start, end = _bar(88), _bar(108)
    old = [_tempo()]
    new = apply_suggestion(old, [_suggestion("half", start, end)], 0)

    assert [s.bpm for s in new] == [BPM, BPM / 2, BPM]
    assert [s.source for s in new] == ["manual"] * 3
    assert (new[1].start_ms, new[1].end_ms) == (start, end)
    assert new[1].confidence is None
    old_lines, new_lines = beat_lines(old), beat_lines(new)
    # every line of the new map sits on a line of the old one, to within 0.01 ms
    assert _near_any(new_lines, old_lines, 0.01)
    # outside the span nothing changed at all, inside every other line is left
    outside = [t for t in old_lines if t < start - 1 or t > end + 1]
    assert _near_any(outside, new_lines, 0.01)
    inside_old = [t for t in old_lines if start - 1 <= t < end - 1]
    inside_new = [t for t in new_lines if start - 1 <= t < end - 1]
    assert len(inside_new) * 2 == len(inside_old)
    assert bar_count(bar_lines(new, METER), start, end) * 2 == bar_count(bar_lines(old, METER), start, end) == 20


def test_applying_double_keeps_every_grid_line_and_doubles_the_bars():
    start, end = _bar(20), _bar(36)
    old = [_tempo()]
    new = apply_suggestion(old, [_suggestion("double", start, end)], 0)

    assert new[1].bpm == BPM * 2
    old_lines, new_lines = beat_lines(old), beat_lines(new)
    assert _near_any(old_lines, new_lines, 0.01)
    assert _near_any(new_lines, [t for t in old_lines] + [t + PERIOD / 2 for t in old_lines], 0.01)
    assert bar_count(bar_lines(new, METER), start, end) == 2 * bar_count(bar_lines(old, METER), start, end)


def test_applying_half_at_the_start_of_a_segment_splits_only_at_its_end():
    old = [_tempo()]
    new = apply_suggestion(old, [_suggestion("half", ANCHOR, _bar(40))], 0)
    assert [s.bpm for s in new] == [BPM / 2, BPM]
    assert new[0].anchor_ms == ANCHOR
    assert _near_any(beat_lines(new), beat_lines(old), 0.01)


def test_a_felt_section_beside_the_span_stays_with_its_side():
    felt = RatioMergedSection(start_ms=20000.0, end_ms=26000.0, bpm=195.0, ratio="3/4", fit=1.0)
    old = [_tempo().model_copy(update={"ratio_merged": [felt]})]
    new = apply_suggestion(old, [_suggestion("half", _bar(40), _bar(60))], 0)
    assert [len(s.ratio_merged) for s in new] == [1, 0, 0]


def test_a_retimed_span_cant_be_applied():
    old = [_tempo(bpm=130.0)]
    with pytest.raises(SuggestionError, match="made on"):
        apply_suggestion(old, [_suggestion("half", _bar(40), _bar(60))], 0)


def test_a_decided_suggestion_cant_be_applied_again():
    with pytest.raises(SuggestionError, match="already dismissed"):
        apply_suggestion([_tempo()], [_suggestion("half", _bar(40), _bar(60), status="dismissed")], 0)


def test_applying_a_fold_puts_the_outro_on_its_neighbours_grid():
    # real_c's map, 3 segments with the outro at 292.75 and 267.87
    main = _tempo(start=1143.354, end=114338.412, bpm=219.9965, anchor=1143.354)
    outro = [
        _tempo(start=114338.412, end=116775.817, bpm=292.7542, anchor=114338.412),
        _tempo(start=116775.817, end=122019.4, bpm=267.871, anchor=116775.817),
    ]
    fold = _suggestion("fold", 114338.412, 122019.4, grid_bpm=292.7542)
    new = apply_suggestion([main, *outro], [fold], 0)

    (seg,) = new
    assert (seg.start_ms, seg.end_ms, seg.bpm, seg.anchor_ms) == (1143.354, 122019.4, 219.9965, 1143.354)
    assert seg.source == "manual" and seg.confidence is None
    assert beat_lines([main], to_ms=114000.0) == beat_lines(new, to_ms=114000.0)


# --- re-analysis ---


def test_a_dismissed_suggestion_stays_dismissed_and_isnt_suggested_again():
    dismissed = _suggestion("half", _bar(0), _bar(40), status="dismissed")
    fresh = [_suggestion("half", _bar(0), _bar(40)), _suggestion("half", _bar(88), _bar(108))]
    kept = keep_decided([dismissed, _suggestion("half", _bar(88), _bar(108))], fresh, [_tempo()])

    assert [(s.start_ms, s.status) for s in kept] == [(_bar(0), "dismissed"), (_bar(88), "open")]


def test_a_span_retimed_by_hand_isnt_suggested_again():
    # the user set the first 40 bars to 130 by hand, the rest is still at the grid's bpm
    tempo = [_tempo(end=_bar(40), bpm=BPM / 2, source="manual", confidence=None), _tempo(start=_bar(40), anchor=_bar(40), source="manual")]
    fresh = [_suggestion("half", _bar(0), _bar(40)), _suggestion("half", _bar(88), _bar(108))]
    kept = keep_decided([], fresh, tempo)
    assert [s.start_ms for s in kept] == [_bar(88)]


# --- meter ---


def test_setting_a_meter_makes_it_manual_with_no_confidence():
    (m,) = set_meter(METER, 0, 7, 8)
    assert (m.numerator, m.denominator, m.source, m.confidence) == (7, 8, "manual", None)


def test_splitting_the_meter_lands_on_a_beat_and_merging_keeps_a_hand_set_signature():
    tempo = [_tempo()]
    meter = split_meter(METER, tempo, _bar(10) + 0.4 * PERIOD)
    assert meter[1].start_ms == pytest.approx(_bar(10), abs=0.001)
    assert [m.source for m in meter] == ["manual", "manual"]
    meter = set_meter(meter, 1, 3, 4)
    merged = merge_meter(meter, 0)
    assert len(merged) == 1 and (merged[0].numerator, merged[0].start_ms, merged[0].end_ms) == (3, ANCHOR, END)
    with pytest.raises(MeterEditError):
        merge_meter(merged, 0)


def test_a_manual_meter_survives_re_analysis():
    manual = MeterSegment(start_ms=_bar(10), end_ms=_bar(20), numerator=3, denominator=4, source="manual")
    previous = [METER[0].model_copy(update={"end_ms": _bar(10)}), manual, METER[0].model_copy(update={"start_ms": _bar(20)})]
    fresh = [MeterSegment(start_ms=ANCHOR, end_ms=END, numerator=4, denominator=4, confidence=0.9, source="auto")]

    kept = keep_manual_meter(previous, fresh)
    assert kept[1] == manual
    assert [(m.start_ms, m.end_ms, m.source) for m in kept] == [(ANCHOR, _bar(10), "auto"), (_bar(10), _bar(20), "manual"), (_bar(20), END, "auto")]
