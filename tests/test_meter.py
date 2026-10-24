"""Meter: beats per bar from the downbeats, on beat lists and through the pipeline on click tracks."""

from functools import lru_cache
from pathlib import Path
import tempfile

import numpy as np
import pytest

from backend.analysis.bars import bar_lines
from backend.analysis.meter import MeterConfig, infer_meter
from backend.analysis.pipeline import run_analysis
from backend.analysis.tempo_map import build_tempo_map
from tests.synth import ClickTrackSpec, cached_click_wav


def _beats(bpm, count, lead=1000.0):
    return lead + np.arange(count) * 60000.0 / bpm


def _positions(bar_lengths):
    # madmom style positions, 1 on each downbeat
    return np.concatenate([np.arange(1, n + 1) for n in bar_lengths])


def _meter(times, positions, accents=None, downbeats_known=True, config=MeterConfig()):
    period = float(np.median(np.diff(times)))
    tempo = build_tempo_map(times, positions == 1, times[0], times[-1] + period, downbeats_known=downbeats_known)
    return infer_meter(tempo, times, positions == 1, accents, config)


def _lines(result):
    tempo = [
        type("T", (), {"start_ms": s.start_ms, "end_ms": s.end_ms, "bpm": s.fit.bpm, "anchor_ms": s.anchor_ms})()
        for s in result.tempo.segments
    ]
    return bar_lines(tempo, result.runs)


# --- beat lists ---


def test_four_four_downbeats_give_one_four_four_run():
    times = _beats(128.0, 96)
    result = _meter(times, _positions([4] * 24))

    (run,) = result.runs
    assert (run.numerator, run.denominator) == (4, 4)
    assert run.confidence == pytest.approx(1.0)
    assert (run.start_ms, run.end_ms) == (result.tempo.segments[0].start_ms, result.tempo.segments[0].end_ms)


def test_three_four_downbeats_give_three_four():
    times = _beats(150.0, 96)
    (run,) = _meter(times, _positions([3] * 32)).runs
    assert run.numerator == 3


def test_a_change_of_bar_length_starts_a_new_meter_on_its_first_downbeat():
    times = _beats(140.0, 64 + 60)
    result = _meter(times, _positions([4] * 16 + [3] * 20))

    assert [r.numerator for r in result.runs] == [4, 3]
    assert result.runs[1].start_ms == pytest.approx(times[64], abs=0.01)
    # 16 bars of 4/4 come before it
    lines = _lines(result)
    assert lines.index(min(lines, key=lambda t: abs(t - times[64]))) == 16


def test_a_stray_downbeat_doesnt_make_a_meter_of_its_own():
    # madmom calls one beat in the middle of a bar a downbeat, then carries on in step
    positions = _positions([4] * 24)
    positions[42] = 1
    result = _meter(_beats(128.0, 96), positions)

    (run,) = result.runs
    assert run.numerator == 4


def test_a_bar_that_moves_the_downbeat_restarts_the_bars_where_it_moved():
    # one 3 beat bar, after which the downbeats stay a beat earlier, like a 3/4 bar in a 4/4 song
    times = _beats(128.0, 95)
    result = _meter(times, _positions([4] * 10 + [3] + [4] * 13))

    assert [r.numerator for r in result.runs] == [4, 4]
    assert result.runs[1].start_ms == pytest.approx(times[43], abs=0.01)
    lines = _lines(result)
    assert min(abs(t - times[40]) for t in lines) < 0.01
    assert min(abs(t - times[43]) for t in lines) < 0.01
    assert min(abs(t - times[44]) for t in lines) > 100.0


def test_bars_where_one_beat_is_clearly_louder_win_over_madmoms():
    # madmom says 4/4 all through, the attacks say 7 from beat 64 on
    times = _beats(140.0, 64 + 84)
    loud = np.zeros(len(times), dtype=bool)
    loud[0:64:4] = True
    loud[64::7] = True

    def accents(at_ms):
        idx = np.round((np.asarray(at_ms) - times[0]) / (60000.0 / 140.0)).astype(int)
        return np.where(np.isin(idx, np.flatnonzero(loud)), 1.6, 1.0)

    result = _meter(times, _positions([4] * 37), accents)
    assert [r.numerator for r in result.runs] == [4, 7]
    assert result.runs[1].start_ms == pytest.approx(times[64], abs=0.01)


def test_accents_every_two_bars_dont_make_eight_four():
    # a crash on every other downbeat is a phrase, not a bar of 8
    times = _beats(128.0, 96)

    def accents(at_ms):
        idx = np.round((np.asarray(at_ms) - times[0]) / (60000.0 / 128.0)).astype(int)
        return np.where(idx % 8 == 0, 2.0, 1.0)

    (run,) = _meter(times, _positions([4] * 24), accents).runs
    assert run.numerator == 4


def test_accents_move_the_anchor_onto_beat_one():
    # madmom hears 4/4 starting a beat late, the attacks are 3/4 from the first beat
    times = _beats(150.0, 96)

    def accents(at_ms):
        idx = np.round((np.asarray(at_ms) - times[0]) / 400.0).astype(int)
        return np.where(idx % 3 == 0, 1.6, 1.0)

    result = _meter(times, np.roll(_positions([4] * 24), 1), accents)
    assert [r.numerator for r in result.runs] == [3]
    assert result.tempo.segments[0].anchor_ms == pytest.approx(times[0], abs=0.01)


def test_librosa_meter_has_half_the_confidence():
    times = _beats(128.0, 96)
    (run,) = _meter(times, _positions([4] * 24), downbeats_known=False).runs
    assert run.confidence == pytest.approx(0.5)


# --- click tracks through the pipeline ---


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed, the librosa fallback has its own tests", exc_type=ImportError)


@lru_cache(maxsize=None)
def _analyzed(spec):
    path, track = cached_click_wav(spec)
    with tempfile.TemporaryDirectory() as tmp:
        out = run_analysis(path, Path(tmp), filename=path.name, sha256="0" * 64)
    return out, track


def _report_bar_lines(report):
    return bar_lines(report.tempo_map, report.meter_map)


METERS = [
    pytest.param(ClickTrackSpec(bpm=128, beats=96, lead_silence_s=0.73, accent_downbeats=True), [4], 0, id="4-4"),
    # madmom puts this one in 4/4, the accents put it right
    pytest.param(ClickTrackSpec(bpm=150, beats=96, lead_silence_s=0.61, accent_downbeats=True, beats_per_bar=3), [3], 0, id="3-4"),
    pytest.param(
        ClickTrackSpec(bpm=140, beats=64 + 84, lead_silence_s=0.52, accent_downbeats=True, meter_changes=((64, 7),)),
        [4, 7],
        16,
        id="4-4-to-7-8",
    ),
]


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
@pytest.mark.parametrize("spec, numerators, change_bar", METERS)
def test_click_track_meter_and_change_bar(spec, numerators, change_bar):
    out, track = _analyzed(spec)
    report = out.report

    # 7 beats of the grid come out as 7/4, whether that's 7/8 at twice the bpm is the chart's call
    assert [m.numerator for m in report.meter_map] == numerators
    assert all(m.denominator == 4 and m.source == "auto" for m in report.meter_map)
    assert report.meter_map[0].start_ms == report.tempo_map[0].start_ms
    assert report.meter_map[-1].end_ms == report.tempo_map[-1].end_ms
    assert report.tempo_map[0].anchor_ms == pytest.approx(track.downbeats_ms[0], abs=1.0)
    lines = _report_bar_lines(report)
    # every bar line on an accented click, within the snap's 0.7 ms
    for line in lines:
        assert np.abs(track.downbeats_ms - line).min() < 1.0
    if len(numerators) > 1:
        change = report.meter_map[1].start_ms
        assert lines.index(min(lines, key=lambda t: abs(t - change))) == change_bar
        assert change == pytest.approx(track.onsets_ms[64], abs=1.0)


# the click tracks from milestones 3b and 3c, madmom's downbeats in the section follow the felt
# pulse or the off-beat, the bars have to run on through on the grid
THROUGH = [
    pytest.param(ClickTrackSpec(bpm=270, beats=288, lead_silence_s=0.6113, accent_downbeats=True, patterns=((128, 32, (0.0, 1.5, 3.0)),)), id="dotted"),
    pytest.param(ClickTrackSpec(bpm=270, beats=288, lead_silence_s=0.6113, accent_downbeats=True, patterns=((128, 48, (0.0, 4 / 3, 8 / 3)),)), id="triplet-feel"),
    pytest.param(
        ClickTrackSpec(bpm=260, beats=288, lead_silence_s=0.5531, accent_downbeats=True, patterns=((128, 32, (0.5, 1.5, 2.5, 3.5)),)),
        id="off-beat",
    ),
]


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
@pytest.mark.parametrize("spec", THROUGH)
def test_meter_runs_on_through_felt_sections_and_off_beat_runs(spec):
    out, track = _analyzed(spec)
    report = out.report

    (meter,) = report.meter_map
    assert (meter.numerator, meter.denominator) == (4, 4)
    # every 4th beat of the underlying grid, the section included
    grid = track.content_start_ms + np.arange(0, spec.beats, 4) * 60000.0 / spec.bpm
    lines = np.array(_report_bar_lines(report))
    assert len(lines) == len(grid)
    assert np.abs(lines - grid).max() < 1.0
    # and nothing to retime on a click track
    assert report.notation_suggestions == []
