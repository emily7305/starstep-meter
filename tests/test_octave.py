"""Octave check on click tracks, with the tracked beats built by hand so no tracker is needed."""

from dataclasses import replace

import numpy as np
import pytest

from backend.analysis import octave
from backend.analysis.beats import TrackedBeats
from backend.analysis.octave import (
    DOUBLE_SUPPORT,
    HALVE_SUPPORT,
    OctaveCheck,
    check_octave,
    check_octave_per_segment,
    summary,
)
from backend.analysis.tempo_range import TempoRange
from tests.synth import ClickTrackSpec, click_track

BPM_TOLERANCE = 0.5


def _tracked(times_ms, bar=4, first_downbeat=0, known=True):
    positions = (np.arange(len(times_ms)) - first_downbeat) % bar + 1
    return TrackedBeats(times_ms=np.asarray(times_ms, dtype=np.float64), positions=positions, tracker="madmom", downbeats_known=known)


def _bpm(tracked):
    return 60000.0 / float(np.median(np.diff(tracked.times_ms)))


@pytest.mark.parametrize("bpm", [250.0, 270.0, 300.0])
def test_fast_clicks_tracked_at_half_time_are_doubled(bpm):
    # what madmom does on accented clicks this fast, every other click
    track = click_track(ClickTrackSpec(bpm=bpm, beats=96, accent_downbeats=True))
    half = _tracked(track.onsets_ms[0::2])

    out, check = check_octave(track.samples, track.sample_rate, half)

    assert check.choice == "doubled"
    assert check.midpoint_ratio >= DOUBLE_SUPPORT
    assert _bpm(out) == pytest.approx(bpm, abs=BPM_TOLERANCE)
    # the inserted beats land on the clicks in between
    assert np.abs(out.times_ms - track.onsets_ms[: len(out.times_ms)]).max() < 1.0


def test_doubling_keeps_the_bar_length_and_the_first_downbeat():
    track = click_track(ClickTrackSpec(bpm=270, beats=96, accent_downbeats=True))
    half = _tracked(track.onsets_ms[0::2], first_downbeat=1)

    out, _ = check_octave(track.samples, track.sample_rate, half)

    # the tracker's first downbeat was its second beat, which is now the third
    assert list(out.positions[:6]) == [3, 4, 1, 2, 3, 4]


def test_quiet_offbeats_taken_for_beats_are_halved():
    # eighth notes at a quarter of the beat level, tracked as if they were beats
    track = click_track(ClickTrackSpec(bpm=120, beats=48, accent_downbeats=True, offbeat_level=0.25))
    beats = track.onsets_ms
    doubled = np.sort(np.concatenate((beats, (beats[:-1] + beats[1:]) / 2.0)))

    out, check = check_octave(track.samples, track.sample_rate, _tracked(doubled))

    assert check.choice == "halved"
    assert check.parity_ratio < HALVE_SUPPORT
    assert np.allclose(out.times_ms, beats)


@pytest.mark.parametrize("level", [0.5, 0.7])
def test_offbeats_in_between_leave_the_trackers_choice_alone(level):
    # the ambiguous zone: strong enough eighth notes to make half or double a real question
    track = click_track(ClickTrackSpec(bpm=135, beats=48, accent_downbeats=True, offbeat_level=level))

    out, check = check_octave(track.samples, track.sample_rate, _tracked(track.onsets_ms))

    assert check.choice == "kept"
    assert np.array_equal(out.times_ms, track.onsets_ms)


def test_doubling_stops_at_the_top_of_the_range():
    # offbeats as loud as the beats, but 2 x 170 is past 320
    track = click_track(ClickTrackSpec(bpm=170, beats=48, accent_downbeats=True, offbeat_level=1.0))
    tracked = _tracked(track.onsets_ms)

    kept, check = check_octave(track.samples, track.sample_rate, tracked)
    wider, wide_check = check_octave(track.samples, track.sample_rate, tracked, TempoRange(60.0, 400.0))

    assert check.choice == "kept"
    assert wide_check.choice == "doubled"
    assert _bpm(wider) == pytest.approx(340.0, abs=BPM_TOLERANCE)


def test_halving_stops_at_the_bottom_of_the_range():
    track = click_track(ClickTrackSpec(bpm=120, beats=48, accent_downbeats=True, offbeat_level=0.25))
    beats = track.onsets_ms
    doubled = np.sort(np.concatenate((beats, (beats[:-1] + beats[1:]) / 2.0)))

    _, check = check_octave(track.samples, track.sample_rate, _tracked(doubled), TempoRange(150.0, 320.0))

    assert check.choice == "kept"


def test_the_shift_moves_where_strengths_are_read():
    # beats 12 ms early read the click a little off centre, the shift puts them back
    track = click_track(ClickTrackSpec(bpm=270, beats=96, accent_downbeats=True))
    half = _tracked(track.onsets_ms[0::2] - 11.8)

    _, check = check_octave(track.samples, track.sample_rate, half, shift_ms=11.8)

    assert check.choice == "doubled"


def test_too_few_beats_are_left_alone():
    track = click_track(ClickTrackSpec(bpm=270, beats=12))

    out, check = check_octave(track.samples, track.sample_rate, _tracked(track.onsets_ms[0:12:2]))

    assert check.choice == "kept"
    assert len(out.times_ms) == 6


def test_each_rough_segment_gets_its_own_check():
    # 128 then 192, and the tracker followed the 192 part at 96, every other click
    spec = ClickTrackSpec(bpm=128, beats=160, accent_downbeats=True, tempo_changes=((64, 192.0),))
    track = click_track(spec)
    onsets = track.onsets_ms
    tracked = _tracked(np.concatenate((onsets[:64], onsets[64::2])))

    out, checks = check_octave_per_segment(track.samples, track.sample_rate, tracked, [(0, 64), (64, len(tracked.times_ms))])

    assert [c.choice for c in checks] == ["kept", "doubled"]
    assert len(out.times_ms) == len(onsets) - 1
    assert np.abs(out.times_ms - onsets[: len(out.times_ms)]).max() < 1.0


def test_a_felt_range_still_doubles_onto_a_ratio_of_its_neighbours():
    # 128, 192, 128 with the tracker on every other click of the 192 part. 96 is 3/4 of 128, a
    # felt section by its ratios, but doubling it gives 192, which is still a ratio of 128
    spec = ClickTrackSpec(bpm=128, beats=200, accent_downbeats=True, tempo_changes=((64, 192.0), (160, 128.0)))
    track = click_track(spec)
    onsets = track.onsets_ms
    tracked = _tracked(np.concatenate((onsets[:64], onsets[64:160:2], onsets[160:])))
    ranges = [(0, 64), (64, 112), (112, len(tracked.times_ms))]

    _, checks = check_octave_per_segment(track.samples, track.sample_rate, tracked, ranges, rough_bpm=[128.0, 96.0, 128.0])

    assert [c.choice for c in checks] == ["kept", "doubled", "kept"]


def test_a_felt_range_is_left_as_tracked_when_its_octave_change_lands_off_every_ratio(monkeypatch):
    # the 3-3-2 case: the middle looks like it should be halved, which would make it 3/8 of 270
    tracked = _tracked(np.arange(30) * 222.0)
    middle = tracked.times_ms[10]

    def fake_check(samples, sample_rate, part, tempo_range, shift_ms):
        if part.times_ms[0] != middle:
            return part, OctaveCheck("kept", 270.0, 0.0, 1.0)
        halved = replace(part, times_ms=part.times_ms[0::2], positions=part.positions[0::2])
        return halved, OctaveCheck("halved", 202.5, 0.0, 0.0)

    monkeypatch.setattr(octave, "check_octave", fake_check)
    ranges = [(0, 10), (10, 20), (20, 30)]

    out, checks = check_octave_per_segment(np.zeros(1), 44100, tracked, ranges, rough_bpm=[270.0, 202.5, 270.0])

    assert [c.choice for c in checks] == ["kept", "kept", "kept"]
    # it still says what it saw
    assert checks[1].parity_ratio == 0.0
    assert np.array_equal(out.times_ms, tracked.times_ms)
    # without the rough tempos there's nothing to call it felt, and it's halved
    out, checks = check_octave_per_segment(np.zeros(1), 44100, tracked, ranges)
    assert checks[1].choice == "halved"
    assert len(out.times_ms) == 25


@pytest.mark.parametrize(
    "choices, expected",
    [
        (["kept", "kept"], "kept"),
        (["doubled"], "doubled"),
        (["halved", "halved"], "halved"),
        (["kept", "doubled"], "mixed"),
        (["doubled", "halved"], "mixed"),
    ],
)
def test_summary(choices, expected):
    assert summary([OctaveCheck(c, 120.0, 0.0, 1.0) for c in choices]) == expected
