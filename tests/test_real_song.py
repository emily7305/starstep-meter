"""Regression on one real song's tracked beats, from tests/real/ (git-ignored, never committed).

tests/real/ holds a beats.json and report.json written by the app for a song whose chart is a
constant 270 bpm. Milestone 3 gave it nine segments, with felt-tempo sections at 202.5 (3/4)
and 179.9 (2/3) split out. Without the files these tests skip.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.tempo_map import build_tempo_map

REAL = Path(__file__).parent / "real"


@pytest.fixture(scope="module")
def song():
    beats_path, report_path = REAL / "beats.json", REAL / "report.json"
    if not (beats_path.exists() and report_path.exists()):
        pytest.skip("tests/real/beats.json and report.json not present")
    beats = json.loads(beats_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    times = np.array([b["time_ms"] for b in beats["beats"]])
    downbeats = np.array([b["is_downbeat"] for b in beats["beats"]])
    trim = report["trim"]
    return build_tempo_map(
        times, downbeats, trim["start_ms"], trim["end_ms"], downbeats_known=beats["tracker"] == "madmom"
    ), trim


def test_the_constant_270_song_is_one_segment(song):
    result, trim = song

    (segment,) = result.segments
    assert segment.fit.bpm == pytest.approx(270.0, abs=0.05)
    assert segment.start_ms == trim["start_ms"]
    assert segment.end_ms == trim["end_ms"]


def test_the_felt_sections_are_kept_as_ratio_merges(song):
    result, _ = song

    merges = result.segments[0].ratio_merges
    assert [(round(m.bpm, 1), str(m.ratio)) for m in merges] == [(202.5, "3/4"), (179.9, "2/3")]
    # where milestone 3 put its boundaries, to within a beat
    assert merges[0].start_ms == pytest.approx(44511.1, abs=223.0)
    assert merges[0].end_ms == pytest.approx(58727.9, abs=223.0)
    assert merges[1].start_ms == pytest.approx(86281.0, abs=223.0)
    assert merges[1].end_ms == pytest.approx(91615.6, abs=223.0)
