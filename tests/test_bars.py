"""Bar lines from the tempo map and the meter map, the rule the frontend draws with too."""

from types import SimpleNamespace as NS

import pytest

from backend.analysis.bars import bar_count, bar_lines


def tempo(start, end, bpm, anchor):
    return NS(start_ms=start, end_ms=end, bpm=bpm, anchor_ms=anchor)


def meter(start, end, num, den=4):
    return NS(start_ms=start, end_ms=end, numerator=num, denominator=den)


def test_no_meter_map_is_4_4_from_the_anchor():
    # 120 bpm, a beat is 500 ms and a bar 2000
    lines = bar_lines([tempo(100.0, 10100.0, 120.0, 600.0)])
    assert lines == pytest.approx([600.0, 2600.0, 4600.0, 6600.0, 8600.0])


def test_a_meter_starting_with_the_segment_counts_from_the_anchor():
    lines = bar_lines([tempo(100.0, 10100.0, 120.0, 600.0)], [meter(100.0, 10100.0, 3)])
    assert lines == pytest.approx([600.0 + 1500.0 * k for k in range(7)])


def test_a_meter_change_inside_a_segment_restarts_the_bars_there():
    # 4/4 for two bars, then 7/4 from beat 8 on
    t = [tempo(0.0, 20000.0, 120.0, 0.0)]
    lines = bar_lines(t, [meter(0.0, 4000.0, 4), meter(4000.0, 20000.0, 7)])
    assert lines == pytest.approx([0.0, 2000.0, 4000.0, 7500.0, 11000.0, 14500.0, 18000.0])


def test_a_meter_change_off_the_grid_snaps_to_the_nearest_line():
    t = [tempo(0.0, 10000.0, 120.0, 0.0)]
    lines = bar_lines(t, [meter(0.0, 3010.0, 4), meter(3010.0, 10000.0, 4)])
    # the second meter starts at the beat on 3000, which cuts the second bar short
    assert lines == pytest.approx([0.0, 2000.0, 3000.0, 5000.0, 7000.0, 9000.0])


def test_seven_eight_is_three_and_a_half_beats():
    lines = bar_lines([tempo(0.0, 7100.0, 120.0, 0.0)], [meter(0.0, 7100.0, 7, 8)])
    assert lines == pytest.approx([0.0, 1750.0, 3500.0, 5250.0, 7000.0])


def test_each_tempo_segment_restarts_bars_at_its_anchor():
    # the second segment's anchor sits a beat after its start, so a short bar comes before it
    t = [tempo(0.0, 4000.0, 120.0, 0.0), tempo(4000.0, 9000.0, 60.0, 5000.0)]
    lines = bar_lines(t, [meter(0.0, 9000.0, 4)])
    assert lines == pytest.approx([0.0, 2000.0, 5000.0])


def test_half_the_bpm_makes_bars_twice_as_long():
    full = [tempo(0.0, 16000.0, 240.0, 0.0)]
    halved = [tempo(0.0, 4000.0, 240.0, 0.0), tempo(4000.0, 12000.0, 120.0, 4000.0), tempo(12000.0, 16000.0, 240.0, 12000.0)]
    m = [meter(0.0, 16000.0, 4)]
    assert bar_count(bar_lines(full, m), 4000.0, 12000.0) == 8
    assert bar_count(bar_lines(halved, m), 4000.0, 12000.0) == 4
    # and the lines outside the span don't move
    assert bar_lines(halved, m, 0.0, 3999.0) == pytest.approx(bar_lines(full, m, 0.0, 3999.0))
    assert bar_lines(halved, m, 12000.0, 16000.0) == pytest.approx(bar_lines(full, m, 12000.0, 16000.0))


def test_a_line_just_before_a_tempo_change_belongs_to_the_next_segment():
    # the first segment's bar at 3990 is under a quarter beat before the change at 4000, so it's dropped
    t = [tempo(0.0, 4000.0, 120.0, -10.0), tempo(4000.0, 8000.0, 120.0, 4000.0)]
    assert bar_lines(t) == pytest.approx([-10.0, 1990.0, 4000.0, 6000.0])
