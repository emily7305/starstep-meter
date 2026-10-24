"""Upgrading stored 1.1, 2.0, 2.1 and 2.2 reports and beats files, on the parsed json before validation."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport

SHA = "ab12" * 16


def report_1_1() -> dict:
    # by hand, the way it was stored before 2.0
    return {
        "schema_version": "1.1",
        "source": {
            "filename": "song.mp3",
            "sha256": SHA,
            "duration_ms": 22000.0,
            "sample_rate": 44100,
            "codec": "mp3",
            "decoder_padding_samples": 1105,
        },
        "trim": {"start_ms": 2000.0, "end_ms": 21500.0},
        # not the segment start, so an anchor taken from the start would show
        "beat_offset_ms": 2120.5,
        "tempo_map": [{"start_ms": 2000.0, "bpm": 174.0123, "confidence": 0.93, "source": "auto"}],
        # nothing wrote a meter segment before 2.3
        "meter_map": [],
        "sections": [{"label": "drop", "start_ms": 5000.0, "end_ms": 9000.5, "source": "manual"}],
        "edits": [
            {"field": "beat_offset_ms", "old": 2000.0, "new": 2120.5, "timestamp": "2026-02-01T10:00:00Z"},
            {"field": "tempo_map/0/bpm", "old": 170.0, "new": 174.0123, "timestamp": "2026-02-01T10:05:00Z"},
        ],
    }


def report_2_0() -> dict:
    return {
        "schema_version": "2.0",
        "source": report_1_1()["source"],
        "trim": {"start_ms": 2000.0, "end_ms": 21500.0},
        "tempo_map": [
            {"start_ms": 2000.0, "end_ms": 9000.0, "bpm": 120.0, "anchor_ms": 2010.5, "confidence": 0.9, "source": "auto"},
            {"start_ms": 9000.0, "end_ms": 21500.0, "bpm": 90.0, "anchor_ms": 9000.0, "confidence": None, "source": "manual"},
        ],
        "meter_map": [],
        "sections": [],
        "edits": [{"field": "tempo_map/1/bpm", "old": 80.0, "new": 90.0, "timestamp": "2026-02-01T10:00:00Z"}],
    }


def report_1_0() -> dict:
    # no codec or decoder padding, those only exist in the original file
    old = report_1_1()
    old["schema_version"] = "1.0"
    del old["source"]["codec"]
    del old["source"]["decoder_padding_samples"]
    return old


def beats_1_1() -> dict:
    return {
        "schema_version": "1.1",
        "sha256": SHA,
        "tracker": "madmom",
        "beats": [
            {"time_ms": 2000.0, "raw_time_ms": 1998.5, "residual_ms": 0.25, "bar": 0, "beat_in_bar": 1, "is_downbeat": True},
            {"time_ms": 2500.0, "raw_time_ms": 2501.0, "residual_ms": -0.5, "bar": 0, "beat_in_bar": 2, "is_downbeat": False},
        ],
    }


def beats_2_0() -> dict:
    return {**beats_1_1(), "schema_version": "2.0", "octave": "doubled"}


# --- upgrade_report ---


def test_1_1_report_becomes_2_3_field_by_field() -> None:
    old = report_1_1()

    out = upgrade_report(old)

    assert out["schema_version"] == "2.3"
    assert "beat_offset_ms" not in out
    assert out["tempo_map"] == [
        {
            "start_ms": 2000.0,
            "end_ms": 21500.0,
            "bpm": 174.0123,
            "anchor_ms": 2120.5,
            "confidence": 0.93,
            "source": "auto",
        }
    ]
    # everything else is carried over as it was, the edit log included
    for key in ("source", "trim", "meter_map", "sections", "edits"):
        assert out[key] == old[key]
    assert set(out) == set(old) - {"beat_offset_ms"}


def test_edit_log_keeps_the_old_field_name() -> None:
    out = upgrade_report(report_1_1())

    assert out["edits"][0]["field"] == "beat_offset_ms"


def test_report_upgrade_does_not_modify_its_input() -> None:
    old = report_1_1()

    upgrade_report(old)

    assert old == report_1_1()


@pytest.mark.parametrize("how", ["null", "missing"])
def test_without_a_beat_offset_the_anchor_is_the_segment_start(how: str) -> None:
    old = report_1_1()
    if how == "null":
        old["beat_offset_ms"] = None
    else:
        del old["beat_offset_ms"]

    out = upgrade_report(old)

    assert out["tempo_map"][0]["anchor_ms"] == 2000.0
    assert "beat_offset_ms" not in out


@pytest.mark.parametrize(
    ("trim_end_ms", "expected_end_ms"),
    [(21500.0, 21500.0), (2000.0, 22000.0)],
    ids=["trim end", "trim end not after the segment start"],
)
def test_last_segment_ends_at_the_trim_end_or_else_the_duration(trim_end_ms: float, expected_end_ms: float) -> None:
    old = report_1_1()
    old["trim"]["end_ms"] = trim_end_ms

    out = upgrade_report(old)

    assert out["tempo_map"][0]["end_ms"] == expected_end_ms


def test_a_segment_ends_where_the_next_one_starts() -> None:
    # 1.1 never wrote more than one, but the upgrade shouldn't care
    old = report_1_1()
    old["tempo_map"] = [
        {"start_ms": 2000.0, "bpm": 120.0, "confidence": 0.9, "source": "auto"},
        {"start_ms": 9000.0, "bpm": 90.0, "confidence": None, "source": "manual"},
    ]

    out = upgrade_report(old)

    first, second = out["tempo_map"]
    assert (first["start_ms"], first["end_ms"]) == (2000.0, 9000.0)
    assert (second["start_ms"], second["end_ms"]) == (9000.0, 21500.0)
    # the offset is the first segment's phase, a later one has only its start
    assert (first["anchor_ms"], second["anchor_ms"]) == (2120.5, 9000.0)
    TimingReport.model_validate(out)


def test_upgraded_report_validates_as_a_timing_report() -> None:
    out = upgrade_report(report_1_1())

    report = TimingReport.model_validate(out)

    assert report.schema_version == "2.3"
    segment = report.tempo_map[0]
    assert (segment.start_ms, segment.end_ms, segment.anchor_ms) == (2000.0, 21500.0, 2120.5)
    assert (segment.bpm, segment.confidence, segment.source) == (174.0123, 0.93, "auto")
    assert report.source.codec == "mp3"
    assert [e.field for e in report.edits] == ["beat_offset_ms", "tempo_map/0/bpm"]
    assert report.meter_map == []
    assert report.sections[0].label == "drop"


def test_2_0_report_only_changes_its_version() -> None:
    data = report_2_0()

    out = upgrade_report(data)

    assert out == {**report_2_0(), "schema_version": "2.3"}
    assert data == report_2_0()
    # nothing was ratio merged before 2.1, there were no off-beat runs before 2.2 and no suggestions before 2.3
    report = TimingReport.model_validate(out)
    assert all(s.ratio_merged == [] for s in report.tempo_map)
    assert report.offbeat_runs == []
    assert report.notation_suggestions == []


def test_2_1_report_only_changes_its_version() -> None:
    data = {**report_2_0(), "schema_version": "2.1"}

    assert upgrade_report(data) == {**report_2_0(), "schema_version": "2.3"}
    assert TimingReport.model_validate(upgrade_report(data)).offbeat_runs == []


def test_2_2_report_only_changes_its_version() -> None:
    data = {**report_2_0(), "schema_version": "2.2"}

    out = upgrade_report(data)

    assert out == {**report_2_0(), "schema_version": "2.3"}
    assert data == {**report_2_0(), "schema_version": "2.2"}
    report = TimingReport.model_validate(out)
    assert (report.meter_map, report.notation_suggestions) == ([], [])


def test_a_meter_segment_by_bar_is_left_as_it_was_and_still_fails_validation() -> None:
    # a hand-written one, there's no time to move it to
    meter = [{"start_bar": 0, "numerator": 7, "denominator": 8, "confidence": 0.5, "source": "manual"}]
    data = {**report_2_0(), "schema_version": "2.2", "meter_map": meter}

    out = upgrade_report(data)

    assert out == {**report_2_0(), "schema_version": "2.3", "meter_map": meter}
    with pytest.raises(ValidationError, match="start_bar"):
        TimingReport.model_validate(out)


def test_2_3_report_passes_through_unchanged() -> None:
    data = {**report_2_0(), "schema_version": "2.3"}

    assert upgrade_report(data) == {**report_2_0(), "schema_version": "2.3"}


def test_1_0_report_passes_through_unchanged_and_still_fails_validation() -> None:
    data = report_1_0()

    out = upgrade_report(data)

    assert out == report_1_0()
    with pytest.raises(ValidationError):
        TimingReport.model_validate(out)


@pytest.mark.parametrize(
    "data",
    [None, [], [report_1_1()], "1.1", 1.1, 3, {}, {"schema_version": "3.0"}, {"schema_version": 1.1}],
    ids=["none", "empty list", "list of reports", "string", "float", "int", "empty dict", "future version", "number version"],
)
def test_anything_else_passes_through_unchanged(data: object) -> None:
    before = copy.deepcopy(data)

    assert upgrade_report(data) == before


# --- upgrade_beats ---


def test_1_1_beats_become_2_3_with_the_octave_kept() -> None:
    old = beats_1_1()

    out = upgrade_beats(old)

    assert out == {**beats_1_1(), "schema_version": "2.3", "octave": "kept"}
    assert out["beats"] == old["beats"]


def test_beats_upgrade_does_not_modify_its_input() -> None:
    old = beats_1_1()

    upgrade_beats(old)

    assert old == beats_1_1()


def test_upgraded_beats_validate_as_a_beats_file() -> None:
    beats = BeatsFile.model_validate(upgrade_beats(beats_1_1()))

    assert beats.schema_version == "2.3"
    assert (beats.sha256, beats.tracker, beats.octave) == (SHA, "madmom", "kept")
    assert [b.time_ms for b in beats.beats] == [2000.0, 2500.0]
    assert [b.is_downbeat for b in beats.beats] == [True, False]


def test_2_0_beats_only_change_their_version() -> None:
    out = upgrade_beats(beats_2_0())

    # the octave check's answer is not overwritten
    assert out == {**beats_2_0(), "schema_version": "2.3"}
    assert BeatsFile.model_validate(out).octave == "doubled"


def test_2_1_beats_only_change_their_version() -> None:
    data = {**beats_2_0(), "schema_version": "2.1"}

    assert upgrade_beats(data) == {**beats_2_0(), "schema_version": "2.3"}


def test_2_2_beats_only_change_their_version() -> None:
    data = {**beats_2_0(), "schema_version": "2.2"}

    out = upgrade_beats(data)

    assert out == {**beats_2_0(), "schema_version": "2.3"}
    # there was no grid_features before 2.3, it starts empty
    assert BeatsFile.model_validate(out).grid_features == []


def test_2_3_beats_pass_through_unchanged() -> None:
    data = {**beats_2_0(), "schema_version": "2.3"}

    assert upgrade_beats(data) == {**beats_2_0(), "schema_version": "2.3"}


def test_1_0_beats_pass_through_unchanged_and_still_fail_validation() -> None:
    data = {**beats_1_1(), "schema_version": "1.0"}

    out = upgrade_beats(data)

    assert out == {**beats_1_1(), "schema_version": "1.0"}
    with pytest.raises(ValidationError):
        BeatsFile.model_validate(out)


@pytest.mark.parametrize(
    "data",
    [None, [], [beats_1_1()], "1.1", 1.1, 3, {}, {"schema_version": "3.0"}],
    ids=["none", "empty list", "list of beats files", "string", "float", "int", "empty dict", "future version"],
)
def test_anything_else_passes_through_unchanged_for_beats(data: object) -> None:
    before = copy.deepcopy(data)

    assert upgrade_beats(data) == before
