import numpy as np
import pytest

from backend.analysis.grid_fit import GridFitError
from backend.analysis.tempo_map import TempoMapConfig, build_tempo_map, felt_sections, rough_indices

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


def _map(times, config=TempoMapConfig(), **kwargs):
    return build_tempo_map(times, _four_four(len(times)), times[0], times[-1] + 100.0, config=config, **kwargs)


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
    # segmentation only, the short rule would fold an 8 beat side back in either way
    times = _short_step(0.006)

    assert len(_map(times, consolidate=False).segments) == 2
    assert len(_map(times, TempoMapConfig(bpm_shift_ratio=0.01), consolidate=False).segments) == 1


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

    assert len(_map(times, consolidate=False).segments) == 1
    assert len(_map(times, TempoMapConfig(shift_z=0.5), consolidate=False).segments) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"residual_shift_ms": 0.0},
        {"bpm_shift_ratio": -0.1},
        {"shift_z": 0.0},
        {"smooth_beats": 0},
        {"min_segment_beats": 7},
        {"refine_beats": -1},
        {"ratio_tolerance": 0.0},
        {"ratio_hit_ms": 0.0},
        {"ratio_fit_min": 1.5},
        {"short_min_ms": -1.0},
        {"short_bpm_ratio": 0.5},
        {"weak_coverage": 1.5},
        {"weak_energy_db": 3.0},
    ],
    ids=lambda k: next(iter(k)),
)
def test_bad_config_is_refused(kwargs):
    with pytest.raises(ValueError):
        TempoMapConfig(**kwargs)


# --- consolidation: felt tempos, short and weak segments ---


def _shape(result):
    return [(round(s.fit.bpm, 2), s.stop - s.first) for s in result.segments]


def _felt(middle_bpm=202.5, count=24):
    # 270 with a section in the middle where the tracker followed another pulse, phase continuous
    return _beats([(270.0, 96), (middle_bpm, count), (270.0, 96)])[0]


@pytest.mark.parametrize("ratio", [0.5, 2 / 3, 0.75, 4 / 3, 1.5, 2.0], ids=["1/2", "2/3", "3/4", "4/3", "3/2", "2"])
def test_a_felt_section_folds_into_the_notated_tempo(ratio):
    times = _felt(270.0 * ratio, count=int(24 * max(ratio, 1.0)))

    result = _map(times)

    assert len(result.segments) == 1
    seg = result.segments[0]
    assert seg.fit.bpm == pytest.approx(270.0, abs=BPM_TOLERANCE)
    (merge,) = seg.ratio_merges
    assert merge.bpm == pytest.approx(270.0 * ratio, abs=BPM_TOLERANCE)
    assert merge.fit >= TempoMapConfig().ratio_fit_min
    # the folded beats sit on halves and thirds of the notated grid, so they read as on it
    assert np.abs(result.residuals_ms).max() < 0.01


def test_a_modulation_that_runs_to_the_end_stays_split():
    # 270 -> 202.5 is exactly 3/4 and phase continuous, but nothing comes back to 270
    times, _ = _beats([(270.0, 128), (202.5, 64)])

    assert _shape(_map(times)) == [(270.0, 128), (202.5, 64)]


def test_a_modulation_that_moves_the_phase_stays_split_when_it_comes_back():
    times, _ = _beats([(270.0, 128), (202.5, 64), (270.0, 96)])
    # a quarter beat late into the 202.5 section, so its beats miss the 270 grid's halves and thirds
    times[128:] += 60000.0 / 270.0 / 4.0

    assert len(_map(times).segments) == 3


def test_a_section_longer_than_its_neighbours_is_not_folded():
    # the shorter side is the one that got felt differently, here that's the 128 parts
    times, _ = _beats([(128.0, 64), (192.0, 96), (128.0, 64)])

    assert len(_map(times).segments) == 3


def test_ratio_tolerance_decides_how_near_the_ratio_has_to_be():
    # 0.1% off 3/4, the beats still land on the 270 thirds over 24 beats
    times = _felt(202.5 * 1.001)

    assert len(_map(times).segments) == 1
    assert len(_map(times, TempoMapConfig(ratio_tolerance=0.0005)).segments) == 3


def test_ratio_hit_ms_decides_what_counts_as_on_the_grid():
    # the felt section's instrument sits 6 ms late on every beat
    times = _felt()
    times[96:120] += 6.0

    assert len(_map(times).segments) == 1
    assert len(_map(times, TempoMapConfig(ratio_hit_ms=4.0)).segments) == 3


def test_ratio_fit_min_decides_how_much_of_the_section_has_to_land():
    # every other felt beat is 15 ms late, its own line catches all of them, the 270 grid half
    times = _felt()
    times[97:120:2] += 15.0

    assert len(_map(times).segments) == 3
    merged = _map(times, TempoMapConfig(ratio_fit_min=0.4))
    assert len(merged.segments) == 1
    assert merged.segments[0].ratio_merges[0].fit == pytest.approx(0.5, abs=0.05)


def test_felt_sections_are_the_ones_between_two_dotted_or_triplet_ratios():
    times, _ = _beats([(135.0, 64), (202.5, 32), (270.0, 128), (135.0, 32), (270.0, 64)])
    segments = _map(times, consolidate=False).segments

    # 202.5 is 3/2 of 135 and 3/4 of 270. the 135 between two 270s is half time, the octave check's
    assert felt_sections(segments, TempoMapConfig().ratio_tolerance) == [False, True, False, False, False]


def _intro_artefact():
    # the tracker settling in over the first few seconds, like the real song's first two segments
    return _beats([(268.56, 15), (264.37, 8), (270.0, 174)])[0]


def test_a_short_intro_near_the_tempo_goes_into_it():
    times = _intro_artefact()

    result = _map(times)

    assert _shape(result) == [(270.0, 197)]
    assert result.segments[0].start_ms == times[0]


def test_short_bpm_ratio_decides_how_near_a_short_segment_has_to_be():
    assert len(_map(_intro_artefact(), TempoMapConfig(short_bpm_ratio=0.005)).segments) == 3


def test_short_min_bars_decides_what_is_short():
    # 22 beats 2% slow in the middle is about 5 s, under 8 bars at 270 but over 4 s
    times, _ = _beats([(270.0, 120), (265.0, 22), (270.0, 120)])

    assert len(_map(times).segments) < 3
    assert len(_map(times, TempoMapConfig(short_min_bars=0.0)).segments) == 3


def test_short_min_ms_decides_what_is_short():
    # 13 beats, about 2.9 s
    times, _ = _beats([(270.0, 120), (265.0, 13), (270.0, 120)])
    config = TempoMapConfig(short_min_bars=0.0)

    assert len(_map(times, config).segments) < 3
    assert len(_map(times, TempoMapConfig(short_min_bars=0.0, short_min_ms=2000.0)).segments) == 3


def test_a_slow_drift_is_not_flattened_by_the_short_rule():
    # every piece of a drift is short and near its neighbours, there's no long one to go into
    periods = 60000.0 / np.linspace(120.0, 126.0, 200)
    times = 1000.0 + np.concatenate(([0.0], np.cumsum(periods[:-1])))

    assert len(_map(times).segments) == len(_map(times, consolidate=False).segments)


def _tail(times_parts=((270.0, 200), (285.38, 9))):
    return _beats(list(times_parts))[0]


def test_weak_coverage_folds_in_a_fade_the_tracker_gave_up_on():
    # nine beats over the last 5.7 s, like the real song's outro
    times = _tail()
    end = times[200] + 5694.0

    def tail_map(config=TempoMapConfig()):
        return build_tempo_map(times, _four_four(len(times)), times[0], end, config=config)

    result = tail_map()
    assert _shape(result) == [(270.0, 209)]
    assert result.segments[0].end_ms == end
    assert len(tail_map(TempoMapConfig(weak_coverage=0.2)).segments) == 2


def test_weak_energy_db_folds_in_a_quiet_outro_and_intro():
    outro = _tail()
    intro = _tail(((285.38, 9), (270.0, 200)))

    def quiet_after(t):
        return lambda a, b: -20.0 if a >= t - 1.0 else 0.0

    def quiet_before(t):
        return lambda a, b: -20.0 if b <= t + 1.0 else 0.0

    assert len(_map(outro).segments) == 2
    assert _shape(_map(outro, loudness=quiet_after(outro[200]))) == [(270.0, 209)]
    assert len(_map(outro, TempoMapConfig(weak_energy_db=-30.0), loudness=quiet_after(outro[200])).segments) == 2
    assert len(_map(intro).segments) == 2
    assert _shape(_map(intro, loudness=quiet_before(intro[9]))) == [(270.0, 209)]


def test_consolidate_false_stops_after_segmentation():
    assert len(_map(_felt(), consolidate=False).segments) == 3


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
