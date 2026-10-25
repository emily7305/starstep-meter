import numpy as np
import pytest

from backend.analysis.cross_check import CrossCheckConfig, compare, nearest_distance_ms

PERIOD = 500.0


def _grid(n=64, start=1000.0, period=PERIOD):
    return start + period * np.arange(n)


def _whole(times):
    return [(times[0], times[-1] + PERIOD)]


def test_nearest_distance_finds_the_closer_neighbour():
    others = np.array([0.0, 100.0, 300.0])
    assert nearest_distance_ms(np.array([-5.0, 40.0, 60.0, 290.0, 400.0]), others).tolist() == [5.0, 40.0, 40.0, 10.0, 100.0]
    assert np.isinf(nearest_distance_ms(np.array([1.0]), np.zeros(0))).all()


def test_two_trackers_on_the_same_beats_agree():
    main = _grid()
    check = compare(main, main + 0.4, _whole(main))

    (seg,) = check.segments
    assert seg.disagreement_ms == pytest.approx(0.4)
    assert not seg.flagged
    assert seg.compared == len(main)
    assert check.agrees.all()


@pytest.mark.parametrize("second", [lambda g: g[::2], lambda g: np.sort(np.concatenate((g, g + PERIOD / 2)))], ids=["half", "double"])
def test_half_or_double_tempo_still_agrees(second):
    main = _grid()
    (seg,) = compare(main, second(main), _whole(main)).segments
    assert seg.disagreement_ms == pytest.approx(0.0)
    assert not seg.flagged


def test_half_a_beat_off_is_flagged():
    main = _grid()
    (seg,) = compare(main, main + PERIOD / 2, _whole(main)).segments
    assert seg.disagreement_ms == pytest.approx(PERIOD / 2)
    assert seg.flagged


def test_max_disagreement_ms_decides_what_is_flagged():
    main = _grid()
    second = main + 15.0
    assert compare(main, second, _whole(main)).segments[0].flagged is False
    assert compare(main, second, _whole(main), config=CrossCheckConfig(max_disagreement_ms=10.0)).segments[0].flagged


def test_skipped_spans_are_left_out():
    # librosa half a beat off in the middle, where the analysis expects it (an off-beat run)
    main = _grid()
    second = main.copy()
    second[20:44] += PERIOD / 2
    skip = [(main[20] - 1.0, main[43] + PERIOD / 2 + 1.0)]

    check = compare(main, second, _whole(main), skip=skip)
    assert check.segments[0].disagreement_ms == pytest.approx(0.0)
    assert check.agrees.all()
    assert not ((check.times_ms >= skip[0][0]) & (check.times_ms <= skip[0][1])).any()
    # without the skip, the agreement drops where they differ
    assert not compare(main, second, _whole(main)).agrees.all()


def test_each_segment_gets_its_own_verdict():
    main = _grid(96)
    second = main.copy()
    second[48:] += PERIOD / 2
    segments = [(main[0], main[48]), (main[48], main[-1] + PERIOD)]

    first, last = compare(main, second, segments).segments
    assert not first.flagged
    assert last.flagged


def test_too_few_beats_gives_no_verdict():
    main = _grid()
    (seg,) = compare(main, main[:3], _whole(main)).segments
    assert seg.disagreement_ms is None
    assert not seg.flagged
    assert seg.compared == 0


def test_max_disagreement_ms_has_to_be_positive():
    with pytest.raises(ValueError):
        CrossCheckConfig(max_disagreement_ms=0.0)
