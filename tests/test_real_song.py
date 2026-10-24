"""Regressions on real songs' tracked beats, from tests/real/<song>/ (git-ignored, never committed).

Each folder holds a beats.json and report.json the app wrote for a song whose chart has one
constant tempo, timing data only. The tempo map runs on the beats again, without the audio,
so the loudness and onset checks aren't part of these. A test skips when its song is missing.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.tempo_map import build_tempo_map

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
