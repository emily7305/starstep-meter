"""Regressions on real songs' tracked beats, from tests/real/<song>/ (git-ignored, never committed).

Each folder holds a beats.json and report.json the app wrote for a song whose chart has one
constant tempo, timing data only. The tempo map runs on the beats again, without the audio,
so the loudness and onset checks aren't part of these. A test skips when its song is missing.

The meter and the notation suggestions run again the way the pipeline runs them, on that
rebuilt tempo map, with the band strengths a milestone 4 analysis stores in beats.json. Not on
the report's own map, which can hold manual segments the strengths were never measured on. A
song analyzed before milestone 4 has no strengths, and those tests skip until it's analyzed
again and its files are copied over.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.confidence import assess
from backend.analysis.meter import infer_meter
from backend.analysis.notation import feel_suggestions, fold_suggestions, from_fits, stored_features
from backend.analysis.pipeline import check_against
from backend.analysis.tempo_map import build_tempo_map
from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport

REAL = Path(__file__).parent / "real"


def _song(name):
    folder = REAL / name
    beats_path, report_path = folder / "beats.json", folder / "report.json"
    if not (beats_path.exists() and report_path.exists()):
        pytest.skip(f"tests/real/{name}/beats.json and report.json not present")
    beats = json.loads(beats_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    times = np.array([b["time_ms"] for b in beats["beats"]])
    downbeats = np.array([b["is_downbeat"] for b in beats["beats"]])
    trim = report["trim"]
    result = build_tempo_map(
        times, downbeats, trim["start_ms"], trim["end_ms"], downbeats_known=beats["tracker"] == "madmom"
    )
    return result, trim, times


def _analysis(name):
    """The tempo map, meter and suggestions the pipeline gives, from the song's beats file."""
    folder = REAL / name
    beats_path, report_path = folder / "beats.json", folder / "report.json"
    if not (beats_path.exists() and report_path.exists()):
        pytest.skip(f"tests/real/{name}/beats.json and report.json not present")
    beats = BeatsFile.model_validate(upgrade_beats(json.loads(beats_path.read_text(encoding="utf-8"))))
    report = TimingReport.model_validate(upgrade_report(json.loads(report_path.read_text(encoding="utf-8"))))
    if not beats.grid_features:
        pytest.skip(f"tests/real/{name}/beats.json has no grid_features, analyze the song again with milestone 4")
    times = np.array([b.time_ms for b in beats.beats])
    downbeats = np.array([b.is_downbeat for b in beats.beats])
    start, end = report.trim.start_ms, report.trim.end_ms
    tempo = build_tempo_map(times, downbeats, start, end, downbeats_known=beats.tracker == "madmom")
    features = stored_features(beats)
    meter = infer_meter(tempo, times, downbeats, accents=lambda at: features.lookup(at).sum(axis=1))
    segments = from_fits(meter.tempo.segments)
    found = feel_suggestions(segments, meter.runs, features) + fold_suggestions(segments, features, start, end)
    return meter, found


# --- MisoilePunch♪, 270 with felt sections at 3/4 and 2/3 (milestone 3b) ---


def test_misoilepunch_is_one_segment_at_270():
    result, trim, _ = _song("misoilepunch")

    (segment,) = result.segments
    assert segment.fit.bpm == pytest.approx(270.0, abs=0.05)
    assert (segment.start_ms, segment.end_ms) == (trim["start_ms"], trim["end_ms"])


def test_misoilepunch_keeps_its_felt_sections_as_ratio_merges():
    result, _, _ = _song("misoilepunch")

    merges = result.segments[0].ratio_merges
    assert [(round(m.bpm, 1), str(m.ratio)) for m in merges] == [(202.5, "3/4"), (179.9, "2/3")]
    # where milestone 3 put its boundaries, to within a beat
    assert merges[0].start_ms == pytest.approx(44511.1, abs=223.0)
    assert merges[0].end_ms == pytest.approx(58727.9, abs=223.0)
    assert merges[1].start_ms == pytest.approx(86281.0, abs=223.0)
    assert merges[1].end_ms == pytest.approx(91615.6, abs=223.0)


def test_misoilepunch_gets_no_suggestions_and_stays_4_4():
    # the chart stays 270 all through, the slower feel from about 48 s included. milestone 4 put
    # 3/4 on the last 4 s, the accent rule reading the fade-out
    meter, found = _analysis("misoilepunch")
    assert found == []
    assert [(m.numerator, m.denominator) for m in meter.runs] == [(4, 4)]


# --- ENDYMION, a steady 220 (charted as 440 and 220) that 3b split into 8 ---


def test_endymion_is_220_up_to_its_outro():
    result, trim, _ = _song("endymion")

    main = result.segments[0]
    assert main.fit.bpm == pytest.approx(220.0, abs=0.05)
    assert main.start_ms == trim["start_ms"]
    # the 264 intro feel and the 215, 203 slip at 88 to 95 s are inside it now
    assert main.end_ms == pytest.approx(114338.4, abs=273.0)
    (merge,) = main.ratio_merges
    assert str(merge.ratio) == "6/5"
    assert merge.start_ms == pytest.approx(6051.8, abs=273.0)
    assert merge.end_ms == pytest.approx(13978.3, abs=273.0)


def test_endymion_outro_is_what_is_left():
    # 114.3 s to the end: 4/3 for 12 beats, then 19 beats at about 267.9 that land on no small
    # subdivision of 220. with nothing after it, there's no grid to say it's a felt section, see
    # docs/decisions.md. it's 6% of the song, "match previous" twice puts it on the 220 grid
    result, _, _ = _song("endymion")

    outro = result.segments[1:]
    assert [round(s.fit.bpm, 2) for s in outro] == [292.75, 267.87]
    assert all(s.start_ms >= 114338.0 for s in outro)


def test_endymion_gets_a_fold_suggestion_for_its_outro():
    # 292.75 is a 4/3 feel on the 220 grid's quarters, 267.87 the fade after it. milestone 4
    # pooled both into one median and scored it 0.48, under the cut
    meter, found = _analysis("endymion")
    (fold,) = [s for s in found if s.kind == "fold"]
    main, *outro = meter.tempo.segments
    assert fold.start_ms == pytest.approx(114338.4, abs=1.0)
    assert fold.end_ms == outro[-1].end_ms
    assert fold.suggested_bpm == pytest.approx(main.fit.bpm)
    assert fold.score >= 0.5


def test_endymion_gets_no_half_or_double_suggestions():
    # its drums show no backbeat to read the 440 and 220 parts from, see docs/decisions.md
    # (milestone 4b). none is right until the detector can see them, a wrong one isn't
    _, found = _analysis("endymion")
    assert [s for s in found if s.kind in ("half", "double")] == []


# --- YOUNITHM, a steady 260 (charted as 260 and 130) where madmom took the off-beat four times ---

YOUNITHM_OFFBEAT_MS = [(48663.6, 52872.3), (66260.2, 71986.2), (122322.7, 125286.4), (146294.0, 153711.2)]


def test_younithm_stays_one_segment_at_260():
    result, trim, _ = _song("younithm")

    (segment,) = result.segments
    assert segment.fit.bpm == pytest.approx(260.0, abs=0.05)
    assert (segment.start_ms, segment.end_ms) == (trim["start_ms"], trim["end_ms"])


def test_younithm_marks_its_off_beat_runs():
    result, _, _ = _song("younithm")

    runs = result.segments[0].offbeat_runs
    period = result.segments[0].fit.period_ms
    assert len(runs) == len(YOUNITHM_OFFBEAT_MS)
    for run, (start, end) in zip(runs, YOUNITHM_OFFBEAT_MS):
        assert run.start_ms == pytest.approx(start, abs=period)
        assert run.end_ms == pytest.approx(end, abs=period)


def test_younithm_grid_is_on_the_beats_outside_the_runs():
    result, _, times = _song("younithm")

    inside = np.zeros(len(times), dtype=bool)
    for run in result.segments[0].offbeat_runs:
        inside |= (times >= run.start_ms) & (times <= run.end_ms)
    # milestone 3b had a p95 residual of 110.9 ms, half a beat
    assert np.median(np.abs(result.residuals_ms[~inside])) < 5.0
    assert np.percentile(np.abs(result.residuals_ms), 95) < 25.0


# the chart's measure map, 4/4 with measure 1 on the first downbeat, in measures as charted. the
# chart writes 130 in these and 260 between them, so in beats of the 260 grid a 130 measure is 8
YOUNITHM_CHARTED_AT_130 = [(1, 21), (69, 79), (139, None)]


def _younithm_measure_beat(measure):
    # grid beats of 260 from the first downbeat to where this measure starts
    beats, at = 0, 1
    for first, last in YOUNITHM_CHARTED_AT_130:
        if measure <= first:
            break
        beats += (first - at) * 4
        if last is None or measure <= last:
            return beats + (measure - first) * 8
        beats += (last - first) * 8
        at = last
    return beats + (measure - at) * 4


def _younithm_spans(segment):
    period = segment.fit.period_ms
    spans = []
    for first, last in YOUNITHM_CHARTED_AT_130:
        start = segment.anchor_ms + _younithm_measure_beat(first) * period
        end = segment.end_ms if last is None else segment.anchor_ms + _younithm_measure_beat(last) * period
        spans.append((start, end))
    return spans


def test_younithm_gets_no_suggestion_the_chart_doesnt_have():
    # anything it does suggest has to be half time inside one of the stretches charted at 130
    meter, found = _analysis("younithm")
    (segment,) = meter.tempo.segments
    measure_ms = 8 * segment.fit.period_ms
    spans = _younithm_spans(segment)
    for s in found:
        assert s.kind == "half"
        assert any(start - measure_ms <= s.start_ms and s.end_ms <= end + measure_ms for start, end in spans)


@pytest.mark.xfail(
    strict=True,
    reason="the stretches charted at 130 have no drums and no half-time backbeat, the detector can't see "
    "them in the stored band strengths without also firing on MisoilePunch and click tracks, see "
    "docs/decisions.md (milestone 4b)",
)
def test_younithm_suggestions_follow_the_measure_map():
    meter, found = _analysis("younithm")
    (segment,) = meter.tempo.segments
    measure_ms = 8 * segment.fit.period_ms

    half = [s for s in found if s.kind == "half"]
    assert [s for s in found if s.kind == "double"] == []
    assert len(half) == len(YOUNITHM_CHARTED_AT_130)
    for s, (start, end) in zip(half, _younithm_spans(segment)):
        assert abs(s.start_ms - start) <= measure_ms, f"half from {s.start_ms:.0f}, chart {start:.0f}"
        assert abs(s.end_ms - end) <= measure_ms, f"half to {s.end_ms:.0f}, chart {end:.0f}"
        assert s.suggested_bpm == pytest.approx(segment.fit.bpm / 2)


# --- confidence on the real songs (milestone 6) ---


def _confidence(name):
    """The confidence spans the pipeline gives on the rebuilt tempo map, and the map.

    The cross-check needs librosa's beats, which a beats file has only from milestone 6 on.
    Without them it's the residual part alone.
    """
    meter, _ = _analysis(name)
    beats = BeatsFile.model_validate(upgrade_beats(json.loads((REAL / name / "beats.json").read_text(encoding="utf-8"))))
    times = np.array([b.time_ms for b in beats.beats])
    tempo = meter.tempo
    cross = check_against(tempo, times, np.array(beats.cross_check_beats)) if beats.cross_check_beats else None
    return assess(tempo, times, cross), tempo


def _low_over(conf, start, end):
    return [s for s in conf.spans if s.low and s.start_ms < end and s.end_ms > start]


def test_misoilepunch_felt_sections_are_not_low_confidence():
    conf, tempo = _confidence("misoilepunch")
    merges = tempo.segments[0].ratio_merges
    assert len(merges) == 2
    for m in merges:
        assert _low_over(conf, m.start_ms, m.end_ms) == []


def test_younithm_off_beat_runs_are_not_low_confidence():
    conf, tempo = _confidence("younithm")
    runs = tempo.segments[0].offbeat_runs
    assert len(runs) == len(YOUNITHM_OFFBEAT_MS)
    period = tempo.segments[0].fit.period_ms
    for run in runs:
        # with the ramps either side, up to 8 beats
        assert _low_over(conf, run.start_ms - 8 * period, run.end_ms + 8 * period) == []


def test_low_confidence_on_the_real_songs_is_where_the_trackers_struggled():
    # what's shaded on the three songs: the fades at the end, ENDYMION's intro (its beats about
    # 11 ms late), 79 to 97 s around where madmom lost a beat, and 106 to 110 s where librosa took
    # the off-beat over even eighths. every low span is inside one of these, and each of these has
    # one. see docs/decisions.md (cross-check on the real songs)
    struggles = {
        "misoilepunch": [(128900.0, 134214.0)],
        "younithm": [(169900.0, 174736.0)],
        "endymion": [(1143.0, 5600.0), (79700.0, 97200.0), (105800.0, 110300.0)],
    }
    for name, regions in struggles.items():
        conf, _ = _confidence(name)
        low = [s for s in conf.spans if s.low]
        for s in low:
            assert any(a <= s.start_ms and s.end_ms <= b for a, b in regions), (name, s.start_ms, s.end_ms)
        for a, b in regions:
            assert any(a <= s.start_ms and s.end_ms <= b for s in low), (name, a, b)


def test_the_cross_check_flags_only_endymions_outro():
    # the right segments sit 4 to 7 ms apart on median, the 267.87 outro that the chart has at 220
    # is the one over 20 ms
    flagged = {}
    for name in ("misoilepunch", "younithm", "endymion"):
        beats = BeatsFile.model_validate(upgrade_beats(json.loads((REAL / name / "beats.json").read_text(encoding="utf-8"))))
        if not beats.cross_check_beats:
            pytest.skip(f"tests/real/{name}/beats.json has no cross_check_beats")
        meter, _ = _analysis(name)
        times = np.array([b.time_ms for b in beats.beats])
        check = check_against(meter.tempo, times, np.array(beats.cross_check_beats))
        flagged[name] = [round(c.disagreement_ms or 0.0) for c in check.segments if c.flagged]
        assert all(c.disagreement_ms is not None for c in check.segments)
    assert flagged == {"misoilepunch": [], "younithm": [], "endymion": [21]}
