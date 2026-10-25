"""Notation suggestions: half and double time feel from the drums, and folding an edge stretch."""

from functools import lru_cache
from pathlib import Path
import tempfile

import numpy as np
import pytest

from backend.analysis import pipeline
from backend.analysis.beats import TrackedBeats
from backend.analysis.features import GridFeatures, band_flux, grid_features, half_lines
from backend.analysis.meter import MeterRun
from backend.analysis.notation import (
    NotationConfig,
    Segment,
    _classify,
    feel_suggestions,
    fold_suggestions,
    suggest_from_files,
)
from backend.analysis.pipeline import run_analysis
from tests.synth import ClickTrackSpec, DrumTrackSpec, cached_click_wav, cached_drum_wav, click_track, drum_track


# --- the folded profile ---


def _profile(hits, leak=0.0):
    p = np.full(8, leak)
    for step in hits:
        p[step] = 1.0
    return p


@pytest.mark.parametrize(
    "hits, kind",
    [
        pytest.param((2, 6), "plain", id="snare-on-2-and-4"),
        pytest.param((4,), "half", id="snare-on-3"),
        pytest.param((1, 3, 5, 7), "double", id="snare-on-every-off-beat"),
        pytest.param((0, 2, 4, 6), "double", id="snare-on-every-beat"),
        pytest.param((0, 1, 2, 3, 4, 5, 6, 7), "unknown", id="every-half-beat"),
        pytest.param((0, 2, 5), "unknown", id="no-clear-pattern"),
    ],
)
def test_snare_profiles(hits, kind):
    assert _classify(_profile(hits, leak=0.1), NotationConfig())[0] == kind


def test_a_kick_leaking_into_the_snare_band_lowers_the_score_but_not_the_class():
    clean = _classify(_profile((4,)), NotationConfig())
    leaky = _profile((4,))
    leaky[0] = 0.35
    kind, score, _ = _classify(leaky, NotationConfig())
    assert (clean[0], kind) == ("half", "half")
    assert score == pytest.approx(0.65)


# --- drums on a known grid, no beat tracker ---


def _segment(track, felt=()):
    start = track.first_beat_ms
    end = track.bar_ms(track.spec.bars)
    return Segment(start, end, track.spec.bpm, start, tuple(felt))


def _detect(track, felt=(), meter=None):
    seg = _segment(track, felt)
    flux = band_flux(track.samples.astype(np.float64), track.sample_rate, seg.start_ms, seg.end_ms)
    features = grid_features(flux, half_lines(seg.anchor_ms, seg.period_ms, seg.start_ms, seg.end_ms))
    meter = meter or [MeterRun(seg.start_ms, seg.end_ms, 4, 4, 1.0)]
    return feel_suggestions([seg], meter, features)


def _matches(found, track):
    bar = 4 * track.beat_ms
    assert [s.kind for s in found] == [kind for _, _, kind in track.sections_ms]
    for s, (start, end, kind) in zip(found, track.sections_ms):
        # within a bar is the requirement, on these drums they land on the bar lines
        assert abs(s.start_ms - start) < bar and abs(s.end_ms - end) < bar
        assert s.grid_bpm == pytest.approx(track.spec.bpm, abs=0.01)
        assert s.suggested_bpm == pytest.approx(s.grid_bpm * (0.5 if kind == "half" else 2.0), abs=0.0001)
        assert 0.0 < s.score <= 1.0


SECTIONS = [
    pytest.param(DrumTrackSpec(bpm=130, sections=((16, 8, "half"), (32, 8, "double"))), id="130-half-then-double"),
    pytest.param(DrumTrackSpec(bpm=150, sections=((12, 8, "double"), (28, 10, "half"))), id="150-double-then-half"),
    # charted at twice the pulse for most of it, like real_c
    pytest.param(DrumTrackSpec(bpm=220, sections=((0, 10, "double"), (18, 22, "double"))), id="220-mostly-double"),
    pytest.param(DrumTrackSpec(bpm=260, bars=64, sections=((0, 20, "half"), (40, 10, "half"))), id="260-half-at-the-start"),
]


@pytest.mark.parametrize("spec", SECTIONS)
def test_half_and_double_sections_on_a_known_grid(spec):
    track = drum_track(spec)
    _matches(_detect(track), track)


@pytest.mark.parametrize("bpm", [100.0, 130.0, 174.0, 270.0])
def test_a_steady_pattern_gets_no_suggestions(bpm):
    assert _detect(drum_track(DrumTrackSpec(bpm=bpm))) == []


def test_clicks_on_every_beat_are_no_double_time():
    # something on every beat with no kick under it isn't a backbeat
    track = click_track(ClickTrackSpec(bpm=130, beats=160, lead_silence_s=0.5, accent_downbeats=True))
    start, end = track.content_start_ms, track.content_start_ms + 160 * 60000.0 / 130
    seg = Segment(start, end, 130.0, start)
    flux = band_flux(track.samples.astype(np.float64), track.sample_rate, start, end)
    features = grid_features(flux, half_lines(start, seg.period_ms, start, end))
    assert feel_suggestions([seg], [MeterRun(start, end, 4, 4, 1.0)], features) == []


def test_nothing_is_suggested_inside_a_ratio_merged_section():
    track = drum_track(DrumTrackSpec(bpm=130, sections=((16, 8, "half"), (32, 8, "double"))))
    half_start, half_end, _ = track.sections_ms[0]
    found = _detect(track, felt=[(half_start - 500.0, half_end + 500.0)])
    assert [s.kind for s in found] == ["double"]
    assert all(s.end_ms <= half_start or s.start_ms >= half_end for s in found)


def test_bars_outside_four_four_are_left_alone():
    track = drum_track(DrumTrackSpec(bpm=130, sections=((16, 8, "half"),)))
    seg = _segment(track)
    split = track.bar_ms(12)
    meter = [MeterRun(seg.start_ms, split, 4, 4, 1.0), MeterRun(split, seg.end_ms, 3, 4, 1.0)]
    assert _detect(track, meter=meter) == []


# --- through the pipeline with madmom ---


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed, the librosa fallback has its own tests", exc_type=ImportError)


@lru_cache(maxsize=None)
def _analyzed_drums(spec):
    path, track = cached_drum_wav(spec)
    with tempfile.TemporaryDirectory() as tmp:
        out = run_analysis(path, Path(tmp), filename=path.name, sha256="0" * 64)
    return out, track


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
@pytest.mark.parametrize("spec", SECTIONS[:2])
def test_pipeline_suggests_the_sections_on_a_steady_pulse(spec):
    out, track = _analyzed_drums(spec)
    report = out.report

    # the hats keep madmom on the pulse, so there's one tempo and the feel is left to the suggestions
    (segment,) = report.tempo_map
    assert segment.bpm == pytest.approx(spec.bpm, abs=0.01)
    _matches(report.notation_suggestions, track)
    assert all(s.status == "open" for s in report.notation_suggestions)


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_pipeline_suggests_nothing_on_a_steady_drum_pattern():
    out, _ = _analyzed_drums(DrumTrackSpec(bpm=128))
    assert out.report.notation_suggestions == []


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_the_beats_file_is_enough_to_find_the_suggestions_again():
    out, _ = _analyzed_drums(SECTIONS[0].values[0])
    report, beats = out.report, out.beats

    assert len(beats.grid_features) > 0
    assert all(f.low >= 0 and f.mid >= 0 and f.high >= 0 for f in beats.grid_features)
    again = suggest_from_files(report.tempo_map, report.meter_map, beats, report.trim.start_ms, report.trim.end_ms)
    assert [(s.kind, round(s.start_ms), round(s.end_ms)) for s in again] == [
        (s.kind, round(s.start_ms), round(s.end_ms)) for s in report.notation_suggestions
    ]


# --- fold, with the tracker swapped out so its beats can drift in an outro ---

FOLD_SPEC = ClickTrackSpec(bpm=220, beats=320, lead_silence_s=0.62, accent_downbeats=True)


def _with_beats(monkeypatch, tmp_path, spec, times):
    def fake_track(*_args, **_kwargs):
        # the pipeline adds madmom's bias back before the snap, so take it out here
        raw = times - pipeline.bias_correction_ms("madmom")
        return TrackedBeats(times_ms=raw, positions=np.arange(len(times)) % 4 + 1, tracker="madmom", downbeats_known=True)

    monkeypatch.setattr(pipeline, "track_beats", fake_track)
    path, _ = cached_click_wav(spec)
    work = tmp_path / "work"
    work.mkdir()
    return run_analysis(path, work, filename=path.name, sha256="0" * 64)


@pytest.mark.ffmpeg
def test_an_outro_the_tracker_lost_gets_a_fold_suggestion(monkeypatch, tmp_path):
    # the clicks stay at 220 to the end, the beats drift off at about 267.9 for the last 5.5 s,
    # like real_c's outro. that's no ratio of 220, so the tempo map keeps it apart
    track = click_track(FOLD_SPEC)
    k = 296
    drift = track.onsets_ms[k] + np.arange(1, 40) * 60000.0 / 267.87
    drift = drift[drift < track.content_end_ms - 30.0]
    out = _with_beats(monkeypatch, tmp_path, FOLD_SPEC, np.concatenate((track.onsets_ms[: k + 1], drift)))
    report = out.report

    assert len(report.tempo_map) == 2
    (fold,) = report.notation_suggestions
    assert fold.kind == "fold"
    assert (fold.start_ms, fold.end_ms) == (report.tempo_map[1].start_ms, report.tempo_map[1].end_ms)
    assert fold.suggested_bpm == pytest.approx(220.0, abs=0.01)
    assert fold.grid_bpm == report.tempo_map[1].bpm
    assert fold.score > 0.9


def _outro_features(segments, carried_level, fade_level):
    # the body at 1, the first outro segment louder on the carried 220 grid than off it, the
    # second a fade where every position reads the same, like real_c's last 7.7 s
    main, loud, fade = segments
    positions = np.unique(np.concatenate([
        half_lines(main.anchor_ms, main.period_ms, main.start_ms, fade.end_ms),
        half_lines(loud.anchor_ms, loud.period_ms, loud.start_ms, loud.end_ms),
        half_lines(fade.anchor_ms, fade.period_ms, fade.start_ms, fade.end_ms),
    ]))
    d = (positions - main.anchor_ms) / (main.period_ms / 2)
    on_carried = np.abs(d - np.round(d)) * main.period_ms / 2 < 1.0
    level = np.where(positions < loud.start_ms, 1.0, np.where(positions < fade.start_ms, np.where(on_carried, carried_level, 1.0), fade_level))
    return GridFeatures(times_ms=positions, values=np.column_stack((np.zeros_like(level), level, np.zeros_like(level))))


OUTRO = [
    Segment(0.0, 99818.182, 220.0, 0.0),
    Segment(99818.182, 102218.182, 292.75, 99818.182),
    Segment(102218.182, 107418.182, 267.87, 102218.182),
]


@pytest.mark.parametrize("min_score, folds", [(NotationConfig().fold_min_score, 1), (0.6, 0)], ids=["default", "stricter"])
def test_a_fade_doesnt_outweigh_the_loud_part_of_an_outro(min_score, folds):
    # the fade has more positions than the loud part, scored as one pool it would be a draw at best
    features = _outro_features(OUTRO, carried_level=1.4, fade_level=0.37)
    found = fold_suggestions(OUTRO, features, 0.0, OUTRO[-1].end_ms, config=NotationConfig(fold_min_score=min_score))

    assert len(found) == folds
    if folds:
        (fold,) = found
        assert (fold.start_ms, fold.end_ms, fold.suggested_bpm, fold.grid_bpm) == (99818.182, 107418.182, 220.0, 292.75)
        assert 0.5 < fold.score < 0.6


def test_an_outro_at_its_own_tempo_gets_no_fold_however_quiet_its_end():
    # the loud part catches more on its own grid than on the carried one, a real change
    features = _outro_features(OUTRO, carried_level=0.6, fade_level=0.37)
    assert fold_suggestions(OUTRO, features, 0.0, OUTRO[-1].end_ms) == []


@pytest.mark.ffmpeg
@pytest.mark.parametrize("change_at", [224, 300], ids=["last-30-percent", "last-5-percent"])
def test_a_real_modulation_at_the_end_gets_no_fold_suggestion(monkeypatch, tmp_path, change_at):
    # over the last 30% it's too long to be an outro, over the last 5% the onsets aren't on the
    # 220 grid. the beats are the clicks themselves either way
    spec = ClickTrackSpec(bpm=220, beats=320, lead_silence_s=0.62, accent_downbeats=True, tempo_changes=((change_at, 267.87),))
    track = click_track(spec)
    out = _with_beats(monkeypatch, tmp_path, spec, track.onsets_ms)

    assert [round(s.bpm, 2) for s in out.report.tempo_map] == [220.0, 267.87]
    assert out.report.notation_suggestions == []
