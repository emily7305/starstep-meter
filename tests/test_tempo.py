import numpy as np
import pytest

from backend.analysis import tempo
from backend.analysis.tempo import TempoError, estimate_tempo, onset_hop
from backend.analysis.tempo_range import DEFAULT_MAX_BPM, DEFAULT_MIN_BPM, TempoRange
from backend.analysis.trim import find_trim
from tests.synth import ClickTrackSpec, click_track

BPM_TOLERANCE = 1.0

CASES = [
    pytest.param(ClickTrackSpec(bpm=90), id="90bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=120), id="120bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=150), id="150bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=174), id="174bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=120, sample_rate=48000), id="120bpm-48k"),
    pytest.param(ClickTrackSpec(bpm=174, sample_rate=48000), id="174bpm-48k"),
    # the noise floor and the accents both make the envelope messier
    pytest.param(ClickTrackSpec(bpm=174, noise_floor_db=-90.0, accent_downbeats=True), id="174bpm-noise90-accent"),
    # past the old 240 ceiling. librosa's coarse guess for 270 is 90, a third, so these need the 3x candidates
    pytest.param(ClickTrackSpec(bpm=250, beats=84), id="250bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=270, beats=90, accent_downbeats=True), id="270bpm-44k-accent"),
    pytest.param(ClickTrackSpec(bpm=300, beats=100), id="300bpm-44k"),
    pytest.param(ClickTrackSpec(bpm=270, beats=90, sample_rate=48000), id="270bpm-48k"),
]


@pytest.mark.parametrize("spec", CASES)
def test_bpm_matches_ground_truth(spec):
    track = click_track(spec)
    trim = find_trim(track.samples, track.sample_rate)

    result = estimate_tempo(track.samples, track.sample_rate, trim.start_ms, trim.end_ms)

    ratio = result.bpm / spec.bpm
    # checked first so an octave slip reads as one, not as "off by 87 bpm"
    assert 0.75 < ratio < 1.5, f"octave error, got {result.bpm:.3f} for {spec.bpm:g} (coarse {result.coarse_bpm:.3f})"
    assert abs(result.bpm - spec.bpm) <= BPM_TOLERANCE, f"got {result.bpm:.4f} for {spec.bpm:g}"


@pytest.mark.parametrize("seconds", [0.0, tempo.MIN_DURATION_S / 2, tempo.MIN_DURATION_S - 0.01], ids=["empty", "half", "just-under"])
def test_region_shorter_than_minimum_is_refused(seconds):
    track = click_track(ClickTrackSpec())
    start = 2000.0

    with pytest.raises(TempoError, match="at least"):
        estimate_tempo(track.samples, track.sample_rate, start, start + seconds * 1000.0)


def test_silent_region_has_no_onsets():
    # long enough to pass the length check, so it's the envelope that fails
    silence = np.zeros(5 * 44100, dtype=np.float32)

    with pytest.raises(TempoError, match="no onsets"):
        estimate_tempo(silence, 44100, 0.0, 5000.0)


def test_onset_hop_44k_is_256():
    assert onset_hop(44100) == 256


def test_onset_hop_48k_keeps_the_frame_length():
    hop = onset_hop(48000)
    assert hop == pytest.approx(279, abs=1)
    # same frame length in ms as 256 samples at 44.1 khz, that's the point of scaling it
    assert hop / 48000 == pytest.approx(256 / 44100, rel=0.01)


def test_default_range_is_60_to_320():
    assert (DEFAULT_MIN_BPM, DEFAULT_MAX_BPM) == (60.0, 320.0)
    assert TempoRange() == TempoRange(60.0, 320.0)


@pytest.mark.parametrize("bounds", [(0.0, 320.0), (-5.0, 100.0), (200.0, 200.0), (300.0, 100.0)])
def test_bad_range_is_refused(bounds):
    with pytest.raises(ValueError, match="min_bpm"):
        TempoRange(*bounds)


def test_the_range_caps_the_estimate():
    # with the old 240 ceiling a 270 bpm track can only come out at half
    track = click_track(ClickTrackSpec(bpm=270, beats=90))
    trim = find_trim(track.samples, track.sample_rate)

    capped = estimate_tempo(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, TempoRange(60.0, 240.0))

    assert capped.bpm == pytest.approx(135.0, abs=BPM_TOLERANCE)
    assert all(bpm <= 240.0 for bpm in capped.octave_support)
