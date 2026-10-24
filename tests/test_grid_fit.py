import numpy as np
import pytest

from backend.analysis.grid_fit import MIN_BEATS, GridFitError, fit_grid

BPM_TOLERANCE = 0.01
OFFSET_TOLERANCE_MS = 1.5

PICKUPS = 2
MESSY_BEATS = 400


def _four_four(indices):
    return (indices >= 0) & (indices % 4 == 0)


@pytest.mark.parametrize("bpm, offset_ms", [(120.0, 137.5), (87.5, 2003.25)], ids=["120bpm", "87.5bpm"])
def test_exact_line_is_recovered_exactly(bpm, offset_ms):
    period = 60000.0 / bpm
    idx = np.arange(32)

    fit = fit_grid(offset_ms + period * idx, _four_four(idx))

    assert fit.period_ms == pytest.approx(period, abs=1e-6)
    assert fit.offset_ms == pytest.approx(offset_ms, abs=1e-6)
    assert fit.bpm == pytest.approx(bpm, abs=1e-6)
    assert np.array_equal(fit.indices, idx)
    assert fit.residuals_ms == pytest.approx(np.zeros(32), abs=1e-6)
    assert fit.inliers.all()
    assert fit.confidence == 1.0


@pytest.mark.parametrize("offset_ms", [137.5, 2003.25])
@pytest.mark.parametrize("bpm", [87.5, 120.0, 128.4, 174.0, 212.0])
def test_noisy_beats_give_the_right_bpm_offset_and_indices(bpm, offset_ms):
    rng = np.random.default_rng([round(bpm * 10), round(offset_ms * 100)])
    idx = np.arange(200)
    times = offset_ms + 60000.0 / bpm * idx + rng.normal(0.0, 1.0, len(idx))

    fit = fit_grid(times, _four_four(idx))

    assert fit.bpm == pytest.approx(bpm, abs=BPM_TOLERANCE)
    assert fit.offset_ms == pytest.approx(offset_ms, abs=1.0)
    assert np.array_equal(fit.indices, idx)


def _messy(seed):
    rng = np.random.default_rng(seed)
    bpm = rng.uniform(80.0, 200.0)
    period = 60000.0 / bpm
    # far enough from zero that the pickups stay positive
    offset_ms = rng.uniform(2000.0, 4000.0)
    idx = np.arange(-PICKUPS, MESSY_BEATS)
    times = offset_ms + period * idx + rng.normal(0.0, 2.0, len(idx))

    # pickups and the first downbeat stay, they're what the indices hang off
    dropped = rng.choice(np.flatnonzero(idx >= 1), size=round(0.05 * MESSY_BEATS), replace=False)
    kept = np.setdiff1d(np.arange(len(idx)), dropped)
    times, idx = times[kept], idx[kept]

    moved = rng.choice(np.flatnonzero(idx != 0), size=round(0.03 * MESSY_BEATS), replace=False)
    distance = rng.uniform(30.0, 0.4 * period, len(moved))
    times[moved] += distance * rng.choice([-1.0, 1.0], len(moved))
    displaced = np.zeros(len(times), dtype=bool)
    displaced[moved] = True
    return bpm, offset_ms, times, idx, displaced


@pytest.mark.parametrize("seed", range(20))
def test_messy_beats_with_pickups_keep_indices_and_offset(seed):
    bpm, offset_ms, times, idx, displaced = _messy(seed)

    fit = fit_grid(times, _four_four(idx))

    assert np.array_equal(fit.indices, idx)
    assert fit.offset_ms == pytest.approx(offset_ms, abs=OFFSET_TOLERANCE_MS)
    assert not fit.inliers[displaced].any()
    assert fit.bpm == pytest.approx(bpm, abs=BPM_TOLERANCE)


def test_doubled_beat_is_not_an_inlier():
    rng = np.random.default_rng(11)
    idx = np.arange(64)
    bpm = 140.0
    times = 300.0 + 60000.0 / bpm * idx + rng.normal(0.0, 1.0, len(idx))
    # half a period past beat 20
    doubled = (times[20] + times[21]) / 2.0
    times = np.insert(times, 21, doubled)
    is_downbeat = np.insert(_four_four(idx), 21, False)

    fit = fit_grid(times, is_downbeat)

    assert not fit.inliers[21]
    assert np.delete(fit.inliers, 21).all()
    assert np.array_equal(np.delete(fit.indices, 21), idx)
    assert fit.bpm == pytest.approx(bpm, abs=BPM_TOLERANCE)


def test_unknown_downbeats_halve_the_confidence():
    idx = np.arange(40)
    times = 200.0 + 500.0 * idx
    # four beats 40 ms off the grid, so the known case isn't just 1.0
    times[[10, 17, 25, 33]] += 40.0
    is_downbeat = _four_four(idx)

    known = fit_grid(times, is_downbeat, downbeats_known=True)
    unknown = fit_grid(times, is_downbeat, downbeats_known=False)

    assert known.confidence == pytest.approx(36 / 40)
    assert unknown.confidence == pytest.approx(known.confidence / 2)


@pytest.mark.parametrize("downbeats_known", [True, False])
@pytest.mark.parametrize("seed", range(5))
def test_random_times_have_low_confidence(seed, downbeats_known):
    times = np.sort(np.random.default_rng(seed).uniform(0.0, 30000.0, 60))

    fit = fit_grid(times, np.arange(60) % 4 == 0, downbeats_known=downbeats_known)

    assert fit.confidence < 0.3


def test_fewer_than_min_beats_is_refused():
    idx = np.arange(MIN_BEATS - 1)

    with pytest.raises(GridFitError, match="at least"):
        fit_grid(500.0 * idx, _four_four(idx))


@pytest.mark.parametrize("value", [2500.0, 2400.0], ids=["repeated", "backwards"])
def test_non_increasing_times_are_refused(value):
    idx = np.arange(12)
    times = 500.0 * idx
    times[6] = value

    with pytest.raises(GridFitError, match="increasing"):
        fit_grid(times, _four_four(idx))
