import numpy as np
import pytest

from backend.analysis.grid_fit import GridFitError
from backend.analysis.tempo_map import TempoMapConfig, build_tempo_map, rough_indices

BPM_TOLERANCE = 0.01


def _beats(parts, jitter_ms=0.0, seed=0, start_ms=1000.0):
    """Beat times for (bpm, beats) parts with continuous phase, plus the first beat of each part."""
    times = [start_ms]
    firsts = []
    for bpm, count in parts:
        firsts.append(len(times) - 1)
        for _ in range(count):
            times.append(times[-1] + 60000.0 / bpm)
    times = np.array(times[:-1])
    # true change times before the jitter, that's what the boundary is checked against
    truth = times[firsts].copy()
    if jitter_ms:
        times[1:] += np.random.default_rng(seed).normal(0.0, jitter_ms, len(times) - 1)
    return times, truth


def _four_four(n):
    return np.arange(n) % 4 == 0


def _map(times, config=TempoMapConfig()):
    return build_tempo_map(times, _four_four(len(times)), times[0], times[-1] + 100.0, config=config)


def _assert_matches(result, parts, truth):
    assert len(result.segments) == len(parts), [round(s.fit.bpm, 3) for s in result.segments]
    for seg, (bpm, _), start in zip(result.segments, parts, truth):
        assert seg.fit.bpm == pytest.approx(bpm, abs=BPM_TOLERANCE)
    # the first segment starts at the given start, the others at their first beat
    for seg, (bpm, _), start in zip(result.segments[1:], parts[1:], truth[1:]):
        assert abs(seg.start_ms - start) < 60000.0 / bpm, f"boundary {seg.start_ms:.1f}, truth {start:.1f}"


ONE_CHANGE = [
    pytest.param([(150.0, 96), (200.0, 128)], id="150-200"),
    pytest.param([(174.0, 128), (128.0, 96)], id="174-128"),
    pytest.param([(120.0, 96), (126.0, 96)], id="120-126"),
    pytest.param([(270.0, 160), (135.0, 64)], id="270-135"),
]
TWO_CHANGES = [
    pytest.param([(128.0, 64), (192.0, 96), (128.0, 64)], id="128-192-128"),
    pytest.param([(140.0, 96), (180.0, 96), (210.0, 128)], id="140-180-210"),
]


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("parts", ONE_CHANGE + TWO_CHANGES)
def test_changes_land_within_a_beat_with_the_right_bpm(parts, seed):
    times, truth = _beats(parts, jitter_ms=1.0, seed=seed)

    result = _map(times)

    _assert_matches(result, parts, truth)
    assert result.segments[0].start_ms == times[0]
    assert result.segments[-1].end_ms == times[-1] + 100.0


@pytest.mark.parametrize("parts", ONE_CHANGE + TWO_CHANGES)
def test_the_junction_beat_belongs_to_the_new_tempo(parts):
    # without jitter the first beat of a new tempo sits on both lines, a chart puts the change there
    times, truth = _beats(parts)

    result = _map(times)

    starts = [s.start_ms for s in result.segments[1:]]
    assert starts == pytest.approx(list(truth[1:]), abs=0.01)


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("bpm", [70.0, 120.0, 174.0, 270.0, 300.0])
def test_steady_beats_with_small_jitter_are_one_segment(bpm, seed):
    times, _ = _beats([(bpm, int(64 * bpm / 120) + 32)], jitter_ms=2.0, seed=seed)

    result = _map(times)

    assert len(result.segments) == 1
    assert result.segments[0].fit.bpm == pytest.approx(bpm, abs=0.02)


def _steady(n=200, bpm=120.0, jitter_ms=2.0, seed=0):
    times, _ = _beats([(bpm, n)], jitter_ms=jitter_ms, seed=seed)
    return times


@pytest.mark.parametrize(
    "disturb",
    [
        pytest.param(lambda t: t.__setitem__(slice(80, 84), t[80:84] + 12.0), id="4-beats-12ms-late"),
        pytest.param(lambda t: t.__setitem__(slice(80, 86), t[80:86] + [6, 12, 15, 12, 6, 3]), id="6-beat-rubato"),
        pytest.param(lambda t: t.__setitem__(slice(100, None), t[100:] + 6.0), id="6ms-phase-step"),
        pytest.param(lambda t: t.__setitem__([20, 61, 62, 140], t[[20, 61, 62, 140]] + [15, -18, 17, -12]), id="displaced"),
    ],
)
def test_small_fluctuations_dont_make_a_change(disturb):
    times = _steady()
    disturb(times)

    result = _map(times)

    assert len(result.segments) == 1
    assert result.segments[0].fit.bpm == pytest.approx(120.0, abs=0.02)


def test_dropped_and_doubled_beats_dont_make_a_change():
    times = np.delete(_steady(), [30, 31, 90, 150])
    times = np.insert(times, 120, (times[119] + times[120]) / 2.0)

    result = _map(times)

    assert len(result.segments) == 1


def test_two_displaced_neighbours_dont_split_the_song():
    # 0.34 + 0.25 of a period off on two beats in a row, enough to slip the rough indices
    times = _steady()
    times[50] += 170.0
    times[51] += 125.0

    result = _map(times)

    assert len(result.segments) == 1


@pytest.mark.parametrize("jump_ms", [30.0, 250.0], ids=["30ms", "half-beat"])
def test_a_pause_that_moves_the_phase_is_a_new_segment(jump_ms):
    times = _steady()
    times[100:] += jump_ms

    result = _map(times)

    assert len(result.segments) == 2
    assert [s.fit.bpm for s in result.segments] == pytest.approx([120.0, 120.0], abs=BPM_TOLERANCE)
    assert result.segments[1].start_ms == pytest.approx(times[100], abs=5.0)


def test_a_whole_beat_left_out_is_not_a_change():
    # a gap of two periods is the same grid, the rough indices count it as two beats
    times = np.delete(_steady(), 100)

    result = _map(times)

    assert len(result.segments) == 1
    assert result.indices[100] - result.indices[99] == 2


def test_slow_drift_is_split_until_the_grid_holds():
    # 120 -> 126 over 200 beats, each step is under the bpm ratio but one line drifts far off
    periods = 60000.0 / np.linspace(120.0, 126.0, 200)
    times = 1000.0 + np.concatenate(([0.0], np.cumsum(periods[:-1])))

    result = _map(times)

    assert len(result.segments) > 2
    assert np.abs(result.residuals_ms).max() <= TempoMapConfig().residual_shift_ms


# --- thresholds in the config ---


def _short_step(ratio):
    # 8 beats either side, the joint line stays within a few ms so only the bpm ratio can split it
    return _beats([(120.0, 8), (120.0 * (1 + ratio), 8)])[0]


def test_bpm_shift_ratio_decides_a_short_step():
    times = _short_step(0.006)

    assert len(_map(times).segments) == 2
    assert len(_map(times, TempoMapConfig(bpm_shift_ratio=0.01)).segments) == 1


def test_residual_shift_decides_a_phase_jump():
    times = _steady(jitter_ms=0.5)
    times[100:] += 10.0

    assert len(_map(times).segments) == 2
    assert len(_map(times, TempoMapConfig(residual_shift_ms=15.0)).segments) == 1


def test_min_segment_beats_decides_how_short_a_segment_can_be():
    # a 12 beat section at another tempo in the middle
    times, _ = _beats([(120.0, 40), (150.0, 12), (120.0, 40)])

    assert len(_map(times).segments) == 3
    assert len(_map(times, TempoMapConfig(min_segment_beats=16)).segments) < 3


def test_shift_z_keeps_a_noisy_short_side_from_faking_a_change():
    # 0.6% apart is over the ratio, but on 8 beats a side with 4 ms jitter it's about 3 standard errors
    times, _ = _beats([(120.0, 8), (120.72, 8)], jitter_ms=4.0, seed=3)

    assert len(_map(times).segments) == 1
    assert len(_map(times, TempoMapConfig(shift_z=0.5)).segments) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"residual_shift_ms": 0.0},
        {"bpm_shift_ratio": -0.1},
        {"shift_z": 0.0},
        {"smooth_beats": 0},
        {"min_segment_beats": 7},
        {"refine_beats": -1},
    ],
    ids=lambda k: next(iter(k)),
)
def test_bad_config_is_refused(kwargs):
    with pytest.raises(ValueError):
        TempoMapConfig(**kwargs)


# --- the rest of the result ---


def test_segments_are_contiguous_and_each_beat_has_one():
    parts = [(128.0, 64), (192.0, 96), (128.0, 64)]
    times, _ = _beats(parts, jitter_ms=1.0)

    result = _map(times)

    segs = result.segments
    assert all(a.end_ms == b.start_ms for a, b in zip(segs, segs[1:]))
    assert [s.first for s in segs[1:]] == [s.stop for s in segs[:-1]]
    assert segs[0].first == 0 and segs[-1].stop == len(times)
    assert np.array_equal(np.bincount(result.segment_of_beat), [s.stop - s.first for s in segs])
    assert len(result.residuals_ms) == len(result.indices) == len(times)


def test_each_anchor_is_the_segments_first_downbeat():
    parts = [(150.0, 96), (200.0, 128)]
    times, truth = _beats(parts)
    # the second part starts on beat 96, which is a downbeat in 4/4
    result = build_tempo_map(times, _four_four(len(times)), times[0], times[-1] + 100.0)

    assert result.segments[0].anchor_ms == pytest.approx(times[0], abs=0.01)
    assert result.segments[1].anchor_ms == pytest.approx(truth[1], abs=0.01)
    assert result.indices[96] == 0


def test_unknown_downbeats_halve_the_overall_confidence():
    times = _steady(jitter_ms=0.0)
    known = build_tempo_map(times, _four_four(len(times)), times[0], times[-1], downbeats_known=True)
    unknown = build_tempo_map(times, _four_four(len(times)), times[0], times[-1], downbeats_known=False)

    assert known.confidence == 1.0
    assert unknown.confidence == 0.5


def test_too_few_beats_is_refused():
    with pytest.raises(GridFitError, match="at least"):
        _map(np.arange(7) * 500.0)


def test_rough_indices_count_a_missing_beat_as_two():
    times = np.delete(np.arange(20) * 500.0, 10)

    idx = rough_indices(times)

    assert np.array_equal(idx, np.delete(np.arange(20), 10))
