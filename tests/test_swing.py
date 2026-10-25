"""Swing and gallop on generated click and drum tracks with the grid known, and through the pipeline."""

from functools import lru_cache
from pathlib import Path
import tempfile

import numpy as np
import pytest

from backend.analysis.notation import Segment
from backend.analysis.pipeline import run_analysis
from backend.analysis.swing import SwingConfig, envelope, find_sections
from tests.synth import ClickTrackSpec, DrumTrackSpec, cached_click_wav, click_track, drum_track

TEMPOS = [100.0, 146.0, 220.0, 292.0]


def _clicks(bpm, subdivisions, beats=96, config=SwingConfig()):
    track = click_track(ClickTrackSpec(bpm=bpm, beats=beats, accent_downbeats=True, subdivisions=subdivisions))
    start, end = track.content_start_ms, track.content_end_ms
    env = envelope(track.samples, track.sample_rate, start, end)
    found = find_sections([Segment(start, end, bpm, track.downbeats_ms[0], ())], [], env, config)
    return found, track.onsets_ms[0], 60000.0 / bpm


def _in_beats(found, first_ms, period_ms):
    return [((s.start_ms - first_ms) / period_ms, (s.end_ms - first_ms) / period_ms) for s in found]


@pytest.mark.parametrize("bpm", TEMPOS)
@pytest.mark.parametrize("fractions", [(0.5,), (0.25, 0.5, 0.75), (1 / 3, 2 / 3)], ids=["8ths", "16ths", "triplets"])
def test_straight_notes_give_no_section(bpm, fractions):
    found, _, _ = _clicks(bpm, ((0, 96, fractions),))
    assert found == []


@pytest.mark.parametrize("bpm", TEMPOS)
@pytest.mark.parametrize(
    "fractions, kind, ratio, division",
    [
        ((2 / 3,), "swing", 2.0, 12),
        ((0.5, 0.75), "gallop", 2.0, 16),
        ((0.25, 0.5), "reverse_gallop", 2.0, 16),
        ((2 / 3, 5 / 6), "gallop", 4.0, 24),
        ((1 / 6, 1 / 3), "reverse_gallop", 4.0, 24),
    ],
    ids=["swing", "gallop", "reverse-gallop", "triplet-gallop", "triplet-reverse-gallop"],
)
def test_uneven_notes_are_found_within_a_bar(bpm, fractions, kind, ratio, division):
    # straight 8ths before and after, the section is bars 8 to 15
    found, first, period = _clicks(bpm, ((0, 32, (0.5,)), (32, 32, fractions), (64, 32, (0.5,))))

    (section,) = found
    (start, end), = _in_beats(found, first, period)
    assert (section.kind, section.division) == (kind, division)
    assert start == pytest.approx(32, abs=4)
    assert end == pytest.approx(64, abs=4)
    # at 292 bpm a triplet 16th is 34 ms. the beat click's flux peaks about 3 ms later than the
    # tick's, which is a lot of a 34 ms note: a 2:1 swing reads 1.84 there and a 4:1 gallop 4.6
    assert section.ratio == pytest.approx(ratio, rel=0.2)
    assert section.score > 0.5
    assert section.grid_bpm == bpm


@pytest.mark.parametrize("bpm", [110.0, 146.0, 200.0, 260.0])
@pytest.mark.parametrize(
    "pattern, kind",
    [((2 / 3,), "swing"), ((0.5, 0.75), "gallop"), ((0.25, 0.5), "reverse_gallop")],
    ids=["swing", "gallop", "reverse-gallop"],
)
def test_hats_over_a_backbeat(bpm, pattern, kind):
    # the plain bars have hats on every half beat, quiet on the off-beat like the notation tests'
    track = drum_track(DrumTrackSpec(bpm=bpm, bars=32, hat_patterns=((8, 12, pattern),)))
    end = track.first_beat_ms + 32 * 4 * track.beat_ms
    env = envelope(track.samples, track.sample_rate, track.first_beat_ms, end)

    found = find_sections([Segment(track.first_beat_ms, end, bpm, track.first_beat_ms, ())], [], env)

    (section,) = found
    assert section.kind == kind
    assert section.start_ms == pytest.approx(track.bar_ms(8), abs=4 * track.beat_ms)
    assert section.end_ms == pytest.approx(track.bar_ms(20), abs=4 * track.beat_ms)


def test_plain_drums_give_no_section():
    track = drum_track(DrumTrackSpec(bpm=146.0, bars=32))
    end = track.first_beat_ms + 32 * 4 * track.beat_ms
    env = envelope(track.samples, track.sample_rate, track.first_beat_ms, end)
    assert find_sections([Segment(track.first_beat_ms, end, 146.0, track.first_beat_ms, ())], [], env) == []


@pytest.mark.parametrize("swing_from, found", [(SwingConfig().swing_from, False), (0.58, True)], ids=["default", "0.58"])
def test_a_light_swing_is_left_straight(swing_from, found):
    # 3:2 is too light for a triplet division, a chart writes it as straight 8ths
    sections, _, _ = _clicks(146.0, ((0, 96, (0.6,)),), config=SwingConfig(swing_from=swing_from))
    assert bool(sections) == found


@pytest.mark.parametrize("present, found", [(SwingConfig().present, True), (0.99, False)], ids=["default", "0.99"])
def test_a_note_has_to_stand_out_to_count(present, found):
    # the swung hats read about 0.5 to 0.6 of the beat's onset over the floor on these drums
    track = drum_track(DrumTrackSpec(bpm=146.0, bars=16, hat_patterns=((0, 16, (2 / 3,)),)))
    end = track.first_beat_ms + 16 * 4 * track.beat_ms
    env = envelope(track.samples, track.sample_rate, track.first_beat_ms, end)
    sections = find_sections([Segment(track.first_beat_ms, end, 146.0, track.first_beat_ms, ())], [], env, SwingConfig(present=present))
    assert bool(sections) == found


@pytest.mark.parametrize(
    "present, absent, found", [(SwingConfig().present, SwingConfig().absent, False), (0.6, 0.5, True)], ids=["default", "0.5"]
)
def test_a_note_on_the_half_makes_it_not_swing(present, absent, found):
    # swung notes with a quieter straight 8th under them: the half reads 0.39 and the late note 0.63
    # of the beat over the floor, so the half isn't empty and it isn't a swing
    track = click_track(ClickTrackSpec(bpm=146.0, beats=64, accent_downbeats=True, subdivisions=((0, 64, (2 / 3,)),)))
    # its beat clicks only make the beats a little louder, the ticks on the half are the point
    half = click_track(ClickTrackSpec(bpm=146.0, beats=64, subdivisions=((0, 64, (0.5,)),), subdivision_level=0.25))
    samples = track.samples + half.samples[: len(track.samples)]
    start, end = track.content_start_ms, track.content_end_ms
    env = envelope(samples, track.sample_rate, start, end)
    sections = find_sections([Segment(start, end, 146.0, track.downbeats_ms[0], ())], [], env, SwingConfig(present=present, absent=absent))
    assert bool(sections) == found


@pytest.mark.parametrize("min_bars, found", [(SwingConfig().min_bars, True), (3, False)], ids=["default", "3"])
def test_two_swung_bars_are_a_section(min_bars, found):
    # one bar alone is a fill, two in a row are where a chart would want the division
    sections, first, period = _clicks(146.0, ((0, 32, (0.5,)), (32, 8, (2 / 3,)), (40, 56, (0.5,))), config=SwingConfig(min_bars=min_bars))
    assert [s.kind for s in sections] == (["swing"] if found else [])
    if found:
        assert _in_beats(sections, first, period) == [(pytest.approx(32, abs=4), pytest.approx(40, abs=4))]


def test_one_swung_bar_isnt_a_section():
    sections, _, _ = _clicks(146.0, ((0, 32, (0.5,)), (32, 4, (2 / 3,)), (36, 60, (0.5,))), config=SwingConfig(min_bars=1))
    assert sections == []


def test_bars_in_a_felt_section_are_left_out():
    # a ratio merged section follows another pulse, its notes say nothing about this grid
    bpm = 146.0
    track = click_track(ClickTrackSpec(bpm=bpm, beats=96, accent_downbeats=True, subdivisions=((32, 32, (2 / 3,)),)))
    start, end = track.content_start_ms, track.content_end_ms
    env = envelope(track.samples, track.sample_rate, start, end)
    felt = ((track.onsets_ms[30], track.onsets_ms[66]),)
    assert find_sections([Segment(start, end, bpm, track.downbeats_ms[0], felt)], [], env) == []


# --- through the pipeline ---


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed, the librosa fallback has its own tests", exc_type=ImportError)


@lru_cache(maxsize=None)
def _analyzed(spec):
    path, track = cached_click_wav(spec)
    with tempfile.TemporaryDirectory() as tmp:
        out = run_analysis(path, Path(tmp), path.name, "0" * 64)
    return out, track


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_pipeline_finds_swing_and_a_gallop_and_nothing_in_the_straight_bars():
    # 16ths, swing, gallop, then 8ths, 32 beats each, over accented beat clicks
    spec = ClickTrackSpec(
        bpm=146.0,
        beats=128,
        lead_silence_s=1.0,
        accent_downbeats=True,
        subdivisions=((0, 32, (0.25, 0.5, 0.75)), (32, 32, (2 / 3,)), (64, 32, (0.5, 0.75)), (96, 32, (0.5,))),
    )
    out, track = _analyzed(spec)
    (segment,) = out.report.tempo_map
    assert segment.bpm == pytest.approx(146.0, abs=0.01)
    bar = 4 * 60000.0 / 146.0

    sections = out.report.subdivision_sections
    assert [(s.kind, s.division) for s in sections] == [("swing", 12), ("gallop", 16)]
    for s, (a, b) in zip(sections, ((32, 64), (64, 96))):
        assert s.start_ms == pytest.approx(track.onsets_ms[0] + a * 60000.0 / 146.0, abs=bar)
        assert s.end_ms == pytest.approx(track.onsets_ms[0] + b * 60000.0 / 146.0, abs=bar)
    # nothing moved, the grid is the beat clicks'
    assert out.report.tempo_map[0].anchor_ms == pytest.approx(track.downbeats_ms[0], abs=2.0)
