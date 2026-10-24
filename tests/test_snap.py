import numpy as np
import pytest

from backend.analysis.beats import MADMOM_BIAS_MS, bias_correction_ms
from backend.analysis.snap import PEAK_FRACTION, onset_strengths, snap_to_onsets
from tests.synth import ClickTrackSpec, _click, click_track

# snapped beats land ~0.73 ms before the true onset, so 1.5 leaves room without hiding a real miss
SNAP_TOLERANCE_MS = 1.5

CASES = [
    pytest.param(ClickTrackSpec(), id="44k"),
    pytest.param(ClickTrackSpec(sample_rate=48000), id="48k"),
    pytest.param(ClickTrackSpec(noise_floor_db=-90.0), id="44k-noise90"),
]

SR = 44100
CLICK_SPEC = ClickTrackSpec()
FULL = CLICK_SPEC.amplitude
# clicks away from the pair under test, they give the median strength floor something to work with
ORDINARY_MS = [400.0, 600.0, 1600.0, 1800.0]
# where the beat under test sits in the beats array
AT = 2


@pytest.mark.parametrize("spec", CASES)
def test_jittered_beats_go_back_onto_the_click(spec):
    track = click_track(spec)
    jitter = np.random.default_rng(7).uniform(-15.0, 15.0, len(track.onsets_ms))

    result = snap_to_onsets(track.samples, track.sample_rate, track.onsets_ms + jitter)

    err = np.abs(result.times_ms - track.onsets_ms)
    assert result.snapped.all()
    assert err.max() <= SNAP_TOLERANCE_MS, f"worst beat off by {err.max():.3f} ms"


def test_beat_with_no_onset_keeps_its_time():
    track = click_track(ClickTrackSpec(lead_silence_s=2.0))
    lead_beat = 1000.0
    tail_beat = track.content_end_ms + 500.0
    real = track.onsets_ms[:8]
    beats = np.concatenate(([lead_beat], real + 8.0, [tail_beat]))

    result = snap_to_onsets(track.samples, track.sample_rate, beats)

    assert result.times_ms[0] == lead_beat
    assert result.times_ms[-1] == tail_beat
    assert not result.snapped[0]
    assert not result.snapped[-1]
    assert result.snapped[1:-1].all()
    assert np.abs(result.times_ms[1:-1] - real).max() <= SNAP_TOLERANCE_MS


@pytest.mark.parametrize("window_ms, snaps", [(20.0, False), (40.0, True)], ids=["window-20", "window-40"])
def test_click_30ms_away_snaps_only_with_a_wide_window(window_ms, snaps):
    track = click_track(ClickTrackSpec())
    click = track.onsets_ms[5]
    early = click - 30.0
    beats = np.concatenate(([early], track.onsets_ms[10:20]))

    result = snap_to_onsets(track.samples, track.sample_rate, beats, window_ms=window_ms)

    assert result.window_ms == window_ms
    assert result.snapped[0] == snaps
    expected = click if snaps else early
    assert result.times_ms[0] == pytest.approx(expected, abs=SNAP_TOLERANCE_MS)


def _signal(clicks):
    shape = _click(SR, CLICK_SPEC.click_freq_hz, CLICK_SPEC.click_ms, CLICK_SPEC.click_decay_ms)
    audio = np.zeros(3 * SR)
    for ms, amplitude in clicks:
        start = int(round(ms / 1000.0 * SR))
        audio[start:start + len(shape)] += shape * amplitude
    return audio.astype(np.float32)


def _snap_beat(clicks, beat_ms, **kwargs):
    audio = _signal(clicks + [(ms, FULL) for ms in ORDINARY_MS])
    beats = np.array([*ORDINARY_MS[:2], beat_ms, *ORDINARY_MS[2:]])
    return snap_to_onsets(audio, SR, beats, **kwargs)


# at 20 the click at 1000 is out of range anyway (22 ms), at 40 both are in and nearest has to decide
@pytest.mark.parametrize("window_ms", [20.0, 40.0])
def test_nearest_of_two_equal_clicks_wins(window_ms):
    result = _snap_beat([(1000.0, FULL), (1030.0, FULL)], 1022.0, window_ms=window_ms)

    assert result.snapped[AT]
    assert result.times_ms[AT] == pytest.approx(1030.0, abs=SNAP_TOLERANCE_MS)


def test_weak_click_nearby_is_ignored_for_the_strong_one():
    quarter = FULL / 4
    # the whole point of the test, a quarter click has to sit under the fraction
    assert quarter / FULL < PEAK_FRACTION

    result = _snap_beat([(1000.0, FULL), (1012.0, quarter)], 1010.0)

    assert result.snapped[AT]
    assert result.times_ms[AT] == pytest.approx(1000.0, abs=SNAP_TOLERANCE_MS)


@pytest.mark.parametrize("window_ms", [0.0, -5.0])
def test_non_positive_window_is_refused(window_ms):
    with pytest.raises(ValueError, match="positive"):
        snap_to_onsets(np.zeros(SR, dtype=np.float32), SR, np.array([500.0]), window_ms=window_ms)


def test_two_dimensional_samples_are_refused():
    with pytest.raises(ValueError, match="mono"):
        snap_to_onsets(np.zeros((2, SR), dtype=np.float32), SR, np.array([500.0]))


# --- bias shift before the search ---


@pytest.mark.parametrize("spec", CASES)
def test_beats_18_to_25_ms_early_snap_once_the_madmom_bias_is_taken_out(spec):
    track = click_track(spec)
    early = np.random.default_rng(5).uniform(18.0, 25.0, len(track.onsets_ms))
    raw = track.onsets_ms - early

    result = snap_to_onsets(track.samples, track.sample_rate, raw, shift_ms=bias_correction_ms("madmom"))

    err = np.abs(result.times_ms - track.onsets_ms)
    assert result.snapped.all()
    assert err.max() <= SNAP_TOLERANCE_MS, f"worst beat off by {err.max():.3f} ms"
    assert result.shift_ms == -MADMOM_BIAS_MS


def test_without_the_shift_beats_past_20_ms_are_out_of_reach():
    # the reason for the shift, the window stays at 20 ms and a 21-25 ms early beat can't get there
    track = click_track(ClickTrackSpec())
    raw = track.onsets_ms - np.linspace(21.0, 25.0, len(track.onsets_ms))

    result = snap_to_onsets(track.samples, track.sample_rate, raw)

    assert not result.snapped.any()


def test_a_shifted_beat_with_nothing_to_snap_to_keeps_the_shifted_time():
    track = click_track(ClickTrackSpec(lead_silence_s=2.0))
    beats = np.concatenate(([1000.0], track.onsets_ms[:8] - 12.0))

    result = snap_to_onsets(track.samples, track.sample_rate, beats, shift_ms=11.8)

    assert not result.snapped[0]
    assert result.times_ms[0] == pytest.approx(1011.8)
    assert result.snapped[1:].all()


def test_onset_strengths_are_zero_in_silence_and_high_on_clicks():
    track = click_track(ClickTrackSpec(lead_silence_s=2.0))

    strengths = onset_strengths(track.samples, track.sample_rate, np.array([1000.0, *track.onsets_ms[:4]]))

    assert strengths[0] == 0.0
    assert (strengths[1:] > 0).all()
