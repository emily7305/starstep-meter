import re
from dataclasses import replace

import numpy as np
import pytest

from backend.analysis import beats
from backend.analysis.beats import BeatTrackingError, track_beats
from backend.analysis.trim import find_trim
from tests.synth import ClickTrackSpec, click_track

BEAT_TOLERANCE_MS = 20.0

# the lead isn't a multiple of madmom's 10 ms frame
SPEC = ClickTrackSpec(bpm=120, beats=40, lead_silence_s=0.1375, accent_downbeats=True)


def _prepare(spec):
    track = click_track(spec)
    trim = find_trim(track.samples, track.sample_rate)
    return track, trim


def _run(spec, tracker):
    track, trim = _prepare(spec)
    result = track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker=tracker)
    return track, result


def _errors_ms(times_ms, onsets_ms):
    # signed, the early bias test needs the direction
    gaps = times_ms[:, None] - onsets_ms[None, :]
    return gaps[np.arange(len(times_ms)), np.abs(gaps).argmin(axis=1)]


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", exc_type=ImportError)


@pytest.fixture(scope="module")
def madmom_run(madmom):
    return _run(SPEC, "madmom")


@pytest.fixture(scope="module")
def librosa_run():
    return _run(SPEC, "librosa")


def test_madmom_finds_every_beat_near_a_click(madmom_run):
    track, result = madmom_run

    assert len(result.times_ms) == SPEC.beats
    assert np.abs(_errors_ms(result.times_ms, track.onsets_ms)).max() <= BEAT_TOLERANCE_MS


def test_madmom_raw_beats_sit_early(madmom_run):
    track, result = madmom_run

    # madmom's early bias, snap is what moves the beats onto the attack
    assert -20.0 <= _errors_ms(result.times_ms, track.onsets_ms).mean() <= 0.0


def test_madmom_first_downbeat_and_positions(madmom_run):
    track, result = madmom_run

    assert result.positions[0] == 1
    assert abs(result.times_ms[0] - track.downbeats_ms[0]) <= BEAT_TOLERANCE_MS
    assert np.array_equal(result.positions, np.arange(len(result.times_ms)) % 4 + 1)


def test_madmom_result_is_labelled(madmom_run):
    _, result = madmom_run

    assert result.tracker == "madmom"
    assert result.downbeats_known is True


@pytest.mark.usefixtures("madmom")
def test_madmom_at_48k_finds_the_same_beats_without_stretching():
    track, result = _run(replace(SPEC, sample_rate=48000), "madmom")

    assert len(result.times_ms) == SPEC.beats
    assert np.abs(_errors_ms(result.times_ms, track.onsets_ms)).max() <= BEAT_TOLERANCE_MS


@pytest.mark.usefixtures("madmom")
def test_madmom_three_beat_bars_cycle_1_2_3():
    _, result = _run(replace(SPEC, beats_per_bar=3), "madmom")

    assert np.array_equal(result.positions, np.arange(len(result.times_ms)) % 3 + 1)


def test_librosa_finds_every_beat_near_a_click(librosa_run):
    track, result = librosa_run

    assert len(result.times_ms) == SPEC.beats
    assert np.abs(_errors_ms(result.times_ms, track.onsets_ms)).max() <= BEAT_TOLERANCE_MS


def test_librosa_positions_are_guessed_from_the_beat_order(librosa_run):
    _, result = librosa_run

    assert np.array_equal(result.positions, np.arange(len(result.times_ms)) % 4 + 1)
    assert result.tracker == "librosa"
    assert result.downbeats_known is False


def test_madmom_requested_but_missing_points_at_the_extra(monkeypatch):
    monkeypatch.setattr(beats, "madmom_available", lambda: False)
    track, trim = _prepare(SPEC)

    with pytest.raises(BeatTrackingError, match=re.escape("pip install -e .[madmom]")):
        track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="madmom")


def test_auto_without_madmom_falls_back_to_librosa(monkeypatch, librosa_run):
    monkeypatch.setattr(beats, "madmom_available", lambda: False)
    _, forced = librosa_run

    _, result = _run(SPEC, "auto")

    assert result.tracker == "librosa"
    assert np.array_equal(result.times_ms, forced.times_ms)


@pytest.mark.usefixtures("madmom")
def test_three_clicks_are_too_few_beats():
    # librosa can't reach the count check with a region this short, the tempo estimate wants 3 s first
    with pytest.raises(BeatTrackingError, match="need at least"):
        _run(replace(SPEC, beats=3), "madmom")


def test_auto_falls_back_to_librosa_when_madmom_is_installed_but_broken(monkeypatch):
    def broken(*_args, **_kwargs):
        raise ImportError("No module named 'pkg_resources'")

    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    # the import check passes, it's the call into madmom that breaks
    monkeypatch.setattr(beats, "madmom_import_error", lambda: None)
    monkeypatch.setattr(beats, "_track_madmom", broken)
    track, trim = _prepare(SPEC)

    result = track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="auto")
    assert result.tracker == "librosa"
    assert not result.downbeats_known

    # asked for madmom by name, a broken install is an error and not a quiet switch
    with pytest.raises(BeatTrackingError, match="doesn't import"):
        track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="madmom")
