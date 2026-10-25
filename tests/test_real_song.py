"""Regressions on real songs' tracked beats, from tests/real/real_a/ ... (git-ignored, never committed).

Each folder holds a beats.json and report.json the app wrote for a song whose chart has one
constant tempo, timing data only. The songs go by neutral ids, which song each one is lives only
in the git-ignored tests/real/SONGS.local.md. The tempo map runs on the beats again, without the audio,
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
from backend.analysis.octave import count_on_grid
from backend.analysis.pipeline import check_against
from backend.analysis.tempo_map import build_tempo_map
from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport

REAL = Path(__file__).parent / "real"
OLDER_THAN_2_5 = ("1.1", "2.0", "2.1", "2.2", "2.3", "2.4")


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
    raw_beats = json.loads(beats_path.read_text(encoding="utf-8"))
    beats = BeatsFile.model_validate(upgrade_beats(raw_beats))
    report = TimingReport.model_validate(upgrade_report(json.loads(report_path.read_text(encoding="utf-8"))))
    if not beats.grid_features:
        pytest.skip(f"tests/real/{name}/beats.json has no grid_features, analyze the song again with milestone 4")
    times = np.array([b.time_ms for b in beats.beats])
    positions = np.array([b.beat_in_bar for b in beats.beats])
    start, end = report.trim.start_ms, report.trim.end_ms
    tempo = build_tempo_map(times, positions == 1, start, end, downbeats_known=beats.tracker == "madmom")
    # before 2.5 a doubled or halved song's positions were counted per beat, the pipeline counts them
    # on the grid now. which rough segments changed isn't in the file, so a whole-song choice only
    if raw_beats["schema_version"] in OLDER_THAN_2_5 and beats.octave in ("doubled", "halved"):
        positions = count_on_grid(positions, np.zeros(len(positions), dtype=np.int64), tempo)
    downbeats = positions == 1
    features = stored_features(beats)
    meter = infer_meter(tempo, times, downbeats, accents=lambda at: features.lookup(at).sum(axis=1))
    segments = from_fits(meter.tempo.segments)
    found = feel_suggestions(segments, meter.runs, features) + fold_suggestions(segments, features, start, end)
    return meter, found


# --- real_a, a constant 270 with felt sections at 3/4 and 2/3 (milestone 3b) ---


def test_real_a_is_one_segment_at_270():
    result, trim, _ = _song("real_a")

    (segment,) = result.segments
    assert segment.fit.bpm == pytest.approx(270.0, abs=0.05)
    assert (segment.start_ms, segment.end_ms) == (trim["start_ms"], trim["end_ms"])


def test_real_a_keeps_its_felt_sections_as_ratio_merges():
    result, _, _ = _song("real_a")

    merges = result.segments[0].ratio_merges
    assert [(round(m.bpm, 1), str(m.ratio)) for m in merges] == [(202.5, "3/4"), (179.9, "2/3")]
    # where milestone 3 put its boundaries, to within a beat
    assert merges[0].start_ms == pytest.approx(44511.1, abs=223.0)
    assert merges[0].end_ms == pytest.approx(58727.9, abs=223.0)
    assert merges[1].start_ms == pytest.approx(86281.0, abs=223.0)
    assert merges[1].end_ms == pytest.approx(91615.6, abs=223.0)


def test_real_a_gets_no_suggestions_and_stays_4_4():
    # the chart stays 270 all through, the slower feel from about 48 s included. milestone 4 put
    # 3/4 on the last 4 s, the accent rule reading the fade-out
    meter, found = _analysis("real_a")
    assert found == []
    assert [(m.numerator, m.denominator) for m in meter.runs] == [(4, 4)]


# --- real_c, a steady 220 (charted as 440 and 220) that 3b split into 8 ---


def test_real_c_is_220_up_to_its_outro():
    result, trim, _ = _song("real_c")

    main = result.segments[0]
    assert main.fit.bpm == pytest.approx(220.0, abs=0.05)
    assert main.start_ms == trim["start_ms"]
    # the 264 intro feel and the 215, 203 slip at 88 to 95 s are inside it now
    assert main.end_ms == pytest.approx(114338.4, abs=273.0)
    (merge,) = main.ratio_merges
    assert str(merge.ratio) == "6/5"
    assert merge.start_ms == pytest.approx(6051.8, abs=273.0)
    assert merge.end_ms == pytest.approx(13978.3, abs=273.0)


def test_real_c_outro_is_what_is_left():
    # 114.3 s to the end: 4/3 for 12 beats, then 19 beats at about 267.9 that land on no small
    # subdivision of 220. with nothing after it, there's no grid to say it's a felt section, see
    # docs/decisions.md. it's 6% of the song, "match previous" twice puts it on the 220 grid
    result, _, _ = _song("real_c")

    outro = result.segments[1:]
    assert [round(s.fit.bpm, 2) for s in outro] == [292.75, 267.87]
    assert all(s.start_ms >= 114338.0 for s in outro)


def test_real_c_gets_a_fold_suggestion_for_its_outro():
    # 292.75 is a 4/3 feel on the 220 grid's quarters, 267.87 the fade after it. milestone 4
    # pooled both into one median and scored it 0.48, under the cut
    meter, found = _analysis("real_c")
    (fold,) = [s for s in found if s.kind == "fold"]
    main, *outro = meter.tempo.segments
    assert fold.start_ms == pytest.approx(114338.4, abs=1.0)
    assert fold.end_ms == outro[-1].end_ms
    assert fold.suggested_bpm == pytest.approx(main.fit.bpm)
    assert fold.score >= 0.5


def test_real_c_gets_no_half_or_double_suggestions():
    # its drums show no backbeat to read the 440 and 220 parts from, see docs/decisions.md
    # (milestone 4b). none is right until the detector can see them, a wrong one isn't
    _, found = _analysis("real_c")
    assert [s for s in found if s.kind in ("half", "double")] == []


# --- real_b, a steady 260 (charted as 260 and 130) where madmom took the off-beat four times ---

REAL_B_OFFBEAT_MS = [(48663.6, 52872.3), (66260.2, 71986.2), (122322.7, 125286.4), (146294.0, 153711.2)]


def test_real_b_stays_one_segment_at_260():
    result, trim, _ = _song("real_b")

    (segment,) = result.segments
    assert segment.fit.bpm == pytest.approx(260.0, abs=0.05)
    assert (segment.start_ms, segment.end_ms) == (trim["start_ms"], trim["end_ms"])


def test_real_b_marks_its_off_beat_runs():
    result, _, _ = _song("real_b")

    runs = result.segments[0].offbeat_runs
    period = result.segments[0].fit.period_ms
    assert len(runs) == len(REAL_B_OFFBEAT_MS)
    for run, (start, end) in zip(runs, REAL_B_OFFBEAT_MS):
        assert run.start_ms == pytest.approx(start, abs=period)
        assert run.end_ms == pytest.approx(end, abs=period)


def test_real_b_grid_is_on_the_beats_outside_the_runs():
    result, _, times = _song("real_b")

    inside = np.zeros(len(times), dtype=bool)
    for run in result.segments[0].offbeat_runs:
        inside |= (times >= run.start_ms) & (times <= run.end_ms)
    # milestone 3b had a p95 residual of 110.9 ms, half a beat
    assert np.median(np.abs(result.residuals_ms[~inside])) < 5.0
    assert np.percentile(np.abs(result.residuals_ms), 95) < 25.0


# the chart's measure map, 4/4 with measure 1 on the first downbeat, in measures as charted. the
# chart writes 130 in these and 260 between them, so in beats of the 260 grid a 130 measure is 8
REAL_B_CHARTED_AT_130 = [(1, 21), (69, 79), (139, None)]


def _real_b_measure_beat(measure):
    # grid beats of 260 from the first downbeat to where this measure starts
    beats, at = 0, 1
    for first, last in REAL_B_CHARTED_AT_130:
        if measure <= first:
            break
        beats += (first - at) * 4
        if last is None or measure <= last:
            return beats + (measure - first) * 8
        beats += (last - first) * 8
        at = last
    return beats + (measure - at) * 4


def _real_b_spans(segment):
    period = segment.fit.period_ms
    spans = []
    for first, last in REAL_B_CHARTED_AT_130:
        start = segment.anchor_ms + _real_b_measure_beat(first) * period
        end = segment.end_ms if last is None else segment.anchor_ms + _real_b_measure_beat(last) * period
        spans.append((start, end))
    return spans


def test_real_b_gets_no_suggestion_the_chart_doesnt_have():
    # anything it does suggest has to be half time inside one of the stretches charted at 130
    meter, found = _analysis("real_b")
    (segment,) = meter.tempo.segments
    measure_ms = 8 * segment.fit.period_ms
    spans = _real_b_spans(segment)
    for s in found:
        assert s.kind == "half"
        assert any(start - measure_ms <= s.start_ms and s.end_ms <= end + measure_ms for start, end in spans)


@pytest.mark.xfail(
    strict=True,
    reason="the stretches charted at 130 have no drums and no half-time backbeat, the detector can't see "
    "them in the stored band strengths without also firing on real_a and click tracks, see "
    "docs/decisions.md (milestone 4b)",
)
def test_real_b_suggestions_follow_the_measure_map():
    meter, found = _analysis("real_b")
    (segment,) = meter.tempo.segments
    measure_ms = 8 * segment.fit.period_ms

    half = [s for s in found if s.kind == "half"]
    assert [s for s in found if s.kind == "double"] == []
    assert len(half) == len(REAL_B_CHARTED_AT_130)
    for s, (start, end) in zip(half, _real_b_spans(segment)):
        assert abs(s.start_ms - start) <= measure_ms, f"half from {s.start_ms:.0f}, chart {start:.0f}"
        assert abs(s.end_ms - end) <= measure_ms, f"half to {s.end_ms:.0f}, chart {end:.0f}"
        assert s.suggested_bpm == pytest.approx(segment.fit.bpm / 2)


# --- real_d, a steady 146 in 4/4 that opens on the downbeat after 8 s of silence ---

# from the owner's chart, made by ear in a chart editor with the mp3 at 146 bpm: offset -6475 ms with
# measure 1 on the first downbeat
REAL_D_CHART_OFFSET_MS = -6475.0


def _mp3_offset(segment, bpm, music_start_ms, padding_ms):
    # what frontend/src/chartSetup.ts gives with the default setting: measure 1 is the bar the music
    # starts in (the last bar line at or before it, a quarter beat of slack), measure 0 a bar before
    period = 60000.0 / bpm
    bar = 4 * period
    n = np.floor((music_start_ms + period / 4 - segment.anchor_ms) / bar)
    measure_1 = segment.anchor_ms + n * bar
    return -(measure_1 - bar) - padding_ms


def test_real_d_is_one_segment_at_twice_146():
    result, trim, _ = _song("real_d")

    (segment,) = result.segments
    # the octave check doubles it, its hats on the off-beats are as strong as the beats
    assert segment.fit.bpm == pytest.approx(2 * 146.0, abs=0.05)
    assert (segment.start_ms, segment.end_ms) == (trim["start_ms"], trim["end_ms"])


def test_real_d_stays_4_4_all_through():
    # madmom added a beat at 62.3 s, in the quiet bars, and the per-beat count of the doubled beats
    # moved every downbeat after it. that came out as a meter restart at 63149 ms, a bar of 2 beats
    meter, found = _analysis("real_d")
    assert [(m.numerator, m.denominator) for m in meter.runs] == [(4, 4)]
    assert found == []


def test_real_d_measure_1_is_where_the_intro_starts():
    meter, _ = _analysis("real_d")
    (segment,) = meter.tempo.segments
    report = json.loads((REAL / "real_d" / "report.json").read_text(encoding="utf-8"))
    beats = json.loads((REAL / "real_d" / "beats.json").read_text(encoding="utf-8"))
    source = report["source"]
    padding_ms = 1000.0 * source["decoder_padding_samples"] / source["sample_rate"]
    music_start = min(report["trim"]["start_ms"], beats["beats"][0]["time_ms"])

    # the bars start on the first beat, not one 146 beat later where madmom put beat 1
    assert segment.anchor_ms == pytest.approx(8078.5, abs=1.0)
    # 146 in the chart, the same anchor halved the way the bpm buttons do. the chart was set by ear
    # about 17 ms later than the grid, the open bias question in docs/decisions.md. a beat off would
    # be 411 ms at 146 and 205 at 292
    at_146 = _mp3_offset(segment, segment.fit.bpm / 2, music_start, padding_ms)
    assert at_146 == pytest.approx(REAL_D_CHART_OFFSET_MS, abs=20.0)
    assert at_146 == pytest.approx(-6457.6, abs=1.0)
    # at 292 it's the same measure 1, a bar there is half as long
    at_292 = _mp3_offset(segment, segment.fit.bpm, music_start, padding_ms)
    assert at_292 == pytest.approx(at_146 - 4 * 60000.0 / segment.fit.bpm, abs=0.01)


@pytest.mark.parametrize("name", ["real_a", "real_b", "real_c", "real_d"])
def test_no_downbeat_shift_on_the_real_songs(name):
    # with the bar positions counted on the grid none of them has a slip left. real_c's restart at
    # 94.7 s and real_d's at 63 s were both per-beat counting, see docs/decisions.md (milestone 7b)
    meter, found = _analysis(name)
    assert meter.shifts == []
    assert [s for s in found if s.kind == "shift"] == []


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


def test_real_a_felt_sections_are_not_low_confidence():
    conf, tempo = _confidence("real_a")
    merges = tempo.segments[0].ratio_merges
    assert len(merges) == 2
    for m in merges:
        assert _low_over(conf, m.start_ms, m.end_ms) == []


def test_real_b_off_beat_runs_are_not_low_confidence():
    conf, tempo = _confidence("real_b")
    runs = tempo.segments[0].offbeat_runs
    assert len(runs) == len(REAL_B_OFFBEAT_MS)
    period = tempo.segments[0].fit.period_ms
    for run in runs:
        # with the ramps either side, up to 8 beats
        assert _low_over(conf, run.start_ms - 8 * period, run.end_ms + 8 * period) == []


def test_low_confidence_on_the_real_songs_is_where_the_trackers_struggled():
    # what's shaded on the three songs: the fades at the end, real_c's intro (its beats about
    # 11 ms late), 79 to 97 s around where madmom lost a beat, and 106 to 110 s where librosa took
    # the off-beat over even eighths. every low span is inside one of these, and each of these has
    # one. see docs/decisions.md (cross-check on the real songs)
    struggles = {
        "real_a": [(128900.0, 134214.0)],
        "real_b": [(169900.0, 174736.0)],
        "real_c": [(1143.0, 5600.0), (79700.0, 97200.0), (105800.0, 110300.0)],
    }
    for name, regions in struggles.items():
        conf, _ = _confidence(name)
        low = [s for s in conf.spans if s.low]
        for s in low:
            assert any(a <= s.start_ms and s.end_ms <= b for a, b in regions), (name, s.start_ms, s.end_ms)
        for a, b in regions:
            assert any(a <= s.start_ms and s.end_ms <= b for s in low), (name, a, b)


def test_the_cross_check_flags_only_real_c_outro():
    # the right segments sit 4 to 7 ms apart on median, the 267.87 outro that the chart has at 220
    # is the one over 20 ms
    flagged = {}
    for name in ("real_a", "real_b", "real_c"):
        # first, it skips when the song's folder isn't there
        meter, _ = _analysis(name)
        beats = BeatsFile.model_validate(upgrade_beats(json.loads((REAL / name / "beats.json").read_text(encoding="utf-8"))))
        if not beats.cross_check_beats:
            pytest.skip(f"tests/real/{name}/beats.json has no cross_check_beats")
        times = np.array([b.time_ms for b in beats.beats])
        check = check_against(meter.tempo, times, np.array(beats.cross_check_beats))
        flagged[name] = [round(c.disagreement_ms or 0.0) for c in check.segments if c.flagged]
        assert all(c.disagreement_ms is not None for c in check.segments)
    assert flagged == {"real_a": [], "real_b": [], "real_c": [21]}
