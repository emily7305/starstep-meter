"""Per segment and per span confidence, on beat lists and through the pipeline on click tracks."""

import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.confidence import ConfidenceConfig, assess, expected_misfits, window_edges
from backend.analysis.cross_check import compare
from backend.analysis.pipeline import run_analysis
from backend.analysis.tempo_map import build_tempo_map
from tests.synth import ClickTrackSpec, cached_click_wav


def _map(times):
    downbeats = np.arange(len(times)) % 4 == 0
    return build_tempo_map(times, downbeats, times[0], times[-1] + 100.0)


def _steady(n=256, bpm=128.0, start=1000.0, jitter_ms=1.0, seed=0):
    period = 60000.0 / bpm
    times = start + period * np.arange(n)
    times[1:] += np.random.default_rng(seed).normal(0.0, jitter_ms, n - 1)
    return times, period


def _messy(times, first, count, ms, seed=1):
    out = times.copy()
    out[first:first + count] += np.random.default_rng(seed).uniform(-ms, ms, count)
    return out


def _spans_over(conf, start, end):
    return [s for s in conf.spans if s.start_ms < end and s.end_ms > start]


def test_a_steady_beat_list_is_confident_everywhere():
    times, _ = _steady()
    conf = assess(_map(times), times)

    assert conf.segments == [pytest.approx(1.0)]
    assert all(s.confidence == pytest.approx(1.0) and not s.low for s in conf.spans)


def test_a_messy_stretch_gets_lower_confidence_than_the_clean_ones():
    times, _ = _steady()
    messy = _messy(times, 96, 48, 25.0)
    result = _map(messy)
    conf = assess(result, messy)

    inside = _spans_over(conf, messy[100], messy[140])
    clean = [s for s in conf.spans if s.end_ms <= messy[90] or s.start_ms >= messy[150]]
    assert inside and clean
    assert max(s.confidence for s in inside) < min(s.confidence for s in clean)
    assert any(s.low for s in inside)
    assert not any(s.low for s in clean)
    # and the segment as a whole comes out lower than a clean one
    assert conf.segments[0] < assess(_map(times), times).segments[0]


def test_spans_are_window_beats_long_from_the_anchor():
    times, _ = _steady(n=200)
    result = _map(times)
    (seg,) = result.segments
    edges = window_edges(seg, 16)

    assert edges[0] == seg.start_ms and edges[-1] == seg.end_ms
    inner = np.diff(edges[1:-1])
    assert np.allclose(inner, 16 * seg.fit.period_ms)
    # every inner edge is a line of the grid
    lines = (np.array(edges[1:-1]) - seg.anchor_ms) / seg.fit.period_ms
    assert np.allclose(lines, np.round(lines), atol=1e-9)
    # no stub under half a window at either end
    half = 8 * seg.fit.period_ms
    assert edges[1] - edges[0] >= half and edges[-1] - edges[-2] >= half


def test_window_beats_decides_the_span_length():
    times, _ = _steady(n=200)
    result = _map(times)
    short = assess(result, times, config=ConfidenceConfig(window_beats=8))
    long = assess(result, times)
    assert len(short.spans) > len(long.spans)


def test_a_felt_section_doesnt_lower_confidence():
    # 270 with a 3/4 felt section in the middle, the tempo map keeps it as a ratio merge
    parts = [(270.0, 96), (202.5, 24), (270.0, 96)]
    times = [1000.0]
    for bpm, count in parts:
        for _ in range(count):
            times.append(times[-1] + 60000.0 / bpm)
    times = np.array(times[:-1])
    result = _map(times)
    (merge,) = result.segments[0].ratio_merges

    conf = assess(result, times)
    assert all(not s.low for s in conf.spans)
    for s in _spans_over(conf, merge.start_ms, merge.end_ms):
        assert s.confidence >= min(1.0, merge.fit) - 1e-9


def test_an_off_beat_run_and_its_ramps_dont_lower_confidence():
    period = 60000.0 / 260.0
    times = 1000.0 + period * np.arange(300)
    # five beats ramping onto the off-beat, 24 beats on it, five ramping back
    ramp = np.linspace(0.0, 0.5, 7)[1:-1]
    times[95:100] += ramp * period
    times[100:124] += period / 2.0
    times[124:129] += ramp[::-1] * period
    result = _map(times)
    assert len(result.segments[0].offbeat_runs) == 1

    _, offbeat = expected_misfits(result, times)
    (left_out,) = offbeat
    # the ramps are left out along with the run
    assert left_out[0] <= times[96] and left_out[1] >= times[127]
    conf = assess(result, times)
    assert all(not s.low for s in conf.spans)
    assert conf.segments == [pytest.approx(1.0)]


def test_ramp_max_beats_bounds_how_far_a_ramp_reaches():
    period = 60000.0 / 260.0
    times = 1000.0 + period * np.arange(300)
    times[100:124] += period / 2.0
    # a long messy stretch right before the run isn't a ramp, only ramp_max_beats of it are left out
    times[70:100] += np.random.default_rng(3).uniform(15.0, 30.0, 30)
    result = _map(times)
    _, ((start, _),) = expected_misfits(result, times, ConfidenceConfig(ramp_max_beats=4))
    assert start == pytest.approx(times[96])


def test_disagreement_lowers_confidence_by_its_weight():
    times, period = _steady()
    result = _map(times)
    second = times.copy()
    second[96:144] += period / 2.0
    cross = compare(times, second, [(s.start_ms, s.end_ms) for s in result.segments])

    conf = assess(result, times, cross)
    inside = _spans_over(conf, times[100], times[140])
    assert all(s.agreement == pytest.approx(0.0) for s in inside[1:-1])
    # full disagreement keeps half of the residual share
    assert all(s.confidence == pytest.approx(0.5) for s in inside[1:-1])
    unweighted = assess(result, times, cross, ConfidenceConfig(agreement_weight=0.0))
    assert [s.confidence for s in unweighted.spans] == [s.confidence for s in assess(result, times).spans]


def test_the_librosa_fallback_halves_the_segment_but_not_the_spans():
    times, _ = _steady()
    downbeats = np.arange(len(times)) % 4 == 0
    result = build_tempo_map(times, downbeats, times[0], times[-1] + 100.0, downbeats_known=False)
    conf = assess(result, times)
    assert conf.segments == [pytest.approx(0.5)]
    assert all(s.confidence == pytest.approx(1.0) for s in conf.spans)


# --- click tracks through the pipeline, madmom plus librosa's cross-check ---


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed, the cross-check only runs next to it", exc_type=ImportError)


@lru_cache(maxsize=None)
def _analyzed(spec):
    path, track = cached_click_wav(spec)
    with tempfile.TemporaryDirectory() as tmp:
        out = run_analysis(path, Path(tmp), filename=path.name, sha256="0" * 64)
    return out, track


CLEAN = ClickTrackSpec(bpm=120, beats=160, lead_silence_s=0.53, accent_downbeats=True)
MESSY = ClickTrackSpec(bpm=120, beats=160, lead_silence_s=0.53, accent_downbeats=True, messy=((64, 32, 25.0),))


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_a_messy_section_on_clicks_gets_lower_confidence():
    out, track = _analyzed(MESSY)
    report = out.report
    period = 60000.0 / 120.0
    start, end = track.onsets_ms[64], track.onsets_ms[95] + period

    (segment,) = report.tempo_map
    # by the middle of each span, the jitter moves the section's edges a little
    inside = [s for s in report.confidence_spans if start <= (s.start_ms + s.end_ms) / 2 <= end]
    clean = [s for s in report.confidence_spans if s.end_ms <= start or s.start_ms >= end]
    assert max(s.confidence for s in inside) < min(s.confidence for s in clean)
    assert any(s.low for s in inside)
    assert not any(s.low for s in clean)
    # the residuals say it, both trackers took the same jittered clicks
    assert all(s.agreement == pytest.approx(1.0) for s in report.confidence_spans)
    clean_out, _ = _analyzed(CLEAN)
    assert segment.confidence < clean_out.report.tempo_map[0].confidence == pytest.approx(1.0)


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_the_cross_check_agrees_on_clean_clicks():
    out, _ = _analyzed(CLEAN)
    check = out.report.cross_check
    assert check is not None and check.tracker == "librosa"
    (seg,) = check.segments
    assert seg.disagreement_ms is not None and seg.disagreement_ms < 1.0
    assert not seg.flagged
    # the second tracker's beats are kept, so the check can run again without the audio
    assert len(out.beats.cross_check_beats) == len(out.second_ms) > 100


FELT_AND_OFFBEAT = [
    pytest.param(ClickTrackSpec(bpm=270, beats=288, lead_silence_s=0.6113, accent_downbeats=True, patterns=((128, 32, (0.0, 1.5, 3.0)),)), id="dotted"),
    pytest.param(ClickTrackSpec(bpm=270, beats=288, lead_silence_s=0.6113, accent_downbeats=True, patterns=((128, 48, (0.0, 4 / 3, 8 / 3)),)), id="triplet-feel"),
    pytest.param(
        ClickTrackSpec(bpm=260, beats=288, lead_silence_s=0.5531, accent_downbeats=True, patterns=((128, 32, (0.5, 1.5, 2.5, 3.5)),)),
        id="off-beat",
    ),
]


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
@pytest.mark.parametrize("spec", FELT_AND_OFFBEAT)
def test_felt_sections_and_off_beat_runs_on_clicks_dont_lower_confidence(spec):
    out, _ = _analyzed(spec)
    report = out.report

    (segment,) = report.tempo_map
    assert segment.ratio_merged or report.offbeat_runs
    assert segment.confidence == pytest.approx(1.0, abs=0.02)
    assert all(s.confidence >= 0.95 for s in report.confidence_spans)
    assert not report.cross_check.segments[0].flagged
