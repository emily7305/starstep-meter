import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.schema.export_schema import BEATS_SCHEMA_PATH, SCHEMA_PATH, main, render_schema
from backend.schema.models import (
    AudioSource,
    Beat,
    BeatsFile,
    Edit,
    MeterSegment,
    Section,
    TempoSegment,
    TimingReport,
    Trim,
)

SHA = "ab12" * 16


def full_report() -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename="song name (final v2).mp3",
            sha256=SHA,
            duration_ms=215432.125,
            sample_rate=48000,
            codec="mp3",
            decoder_padding_samples=1105,
        ),
        trim=Trim(start_ms=1234.5, end_ms=210000.25),
        beat_offset_ms=-12.75,
        tempo_map=[
            TempoSegment(start_ms=1234.5, bpm=174.0123, confidence=0.93, source="auto"),
            TempoSegment(start_ms=90000.0, bpm=87.5, confidence=None, source="manual"),
        ],
        meter_map=[MeterSegment(start_bar=0, numerator=7, denominator=8, confidence=0.5, source="auto")],
        sections=[Section(label="drop", start_ms=20000.0, end_ms=60000.5, source="manual")],
        edits=[
            Edit(
                field="tempo_map/1/bpm",
                old=87.0,
                new=87.5,
                timestamp=datetime(2026, 3, 1, 12, 30, 15, 123000, tzinfo=timezone.utc),
            ),
            # nested old/new on purpose, edits can hold a whole segment or a list of them
            Edit(
                field="sections",
                old=[{"label": "intro", "start_ms": 0.0, "end_ms": 19000.0, "tags": ["a", None], "locked": False}],
                new=[
                    {"label": "intro", "start_ms": 0.0, "end_ms": 20000.0, "tags": [], "locked": True},
                    {"label": "drop", "start_ms": 20000.0, "end_ms": 60000.5, "extra": {"deep": {"er": [1, 2.5, "three"]}}},
                ],
                timestamp=datetime(2026, 3, 2, 8, 0, 0, tzinfo=timezone(timedelta(hours=-5))),
            ),
        ],
    )


def minimal_report() -> TimingReport:
    # one auto segment at the trim start, everything else empty
    return TimingReport(
        source=AudioSource(
            filename="click.wav", sha256=SHA, duration_ms=22000.0, sample_rate=44100, codec="pcm_f32le", decoder_padding_samples=0
        ),
        trim=Trim(start_ms=2000.0, end_ms=21520.0),
        beat_offset_ms=None,
        tempo_map=[TempoSegment(start_ms=2000.0, bpm=120.0, confidence=None, source="auto")],
    )


def valid_payload() -> dict:
    # json-mode dict, deep copied so a test can break one field without touching the next
    return copy.deepcopy(json.loads(full_report().model_dump_json()))


# --- round trips ---


def test_full_report_round_trip_is_lossless():
    report = full_report()

    text = report.model_dump_json(indent=2)
    back = TimingReport.model_validate_json(text)

    assert back == report
    assert back.model_dump_json(indent=2) == text
    # offsets have to survive, naive datetimes would be the quiet way to lose them
    assert back.edits[0].timestamp.utcoffset() == timedelta(0)
    assert back.edits[1].timestamp.utcoffset() == timedelta(hours=-5)
    assert back.edits[1].old == report.edits[1].old
    assert back.edits[1].new == report.edits[1].new


def test_full_report_round_trip_through_a_plain_dict():
    report = full_report()

    payload = json.loads(report.model_dump_json())
    back = TimingReport.model_validate(payload)

    assert back == report
    assert json.loads(back.model_dump_json()) == payload


def test_minimal_report_round_trip_is_lossless():
    report = minimal_report()

    text = report.model_dump_json(indent=2)
    back = TimingReport.model_validate_json(text)

    assert back == report
    assert back.model_dump_json(indent=2) == text
    assert back.schema_version == "1.1"
    assert back.beat_offset_ms is None
    assert back.tempo_map[0].confidence is None
    assert (back.meter_map, back.sections, back.edits) == ([], [], [])


def test_minimal_report_writes_nulls_and_empty_lists_explicitly():
    # the committed schema marks these required, so the file has to carry them
    payload = json.loads(minimal_report().model_dump_json())

    assert payload["schema_version"] == "1.1"
    assert payload["beat_offset_ms"] is None
    assert payload["tempo_map"][0]["confidence"] is None
    assert payload["meter_map"] == []
    assert payload["sections"] == []
    assert payload["edits"] == []


def test_beats_file_round_trip_is_lossless():
    beats = BeatsFile(
        sha256=SHA,
        tracker="madmom",
        beats=[
            Beat(time_ms=1234.5, raw_time_ms=1230.0, residual_ms=0.25, bar=0, beat_in_bar=1, is_downbeat=True),
            Beat(time_ms=1579.3, raw_time_ms=1570.0, residual_ms=-0.5, bar=0, beat_in_bar=2, is_downbeat=False),
            Beat(time_ms=1924.1, raw_time_ms=1920.0, residual_ms=0.0, bar=0, beat_in_bar=3, is_downbeat=False),
            Beat(time_ms=2268.9, raw_time_ms=2260.0, residual_ms=1.125, bar=1, beat_in_bar=1, is_downbeat=True),
        ],
    )

    text = beats.model_dump_json(indent=2)
    back = BeatsFile.model_validate_json(text)

    assert back == beats
    assert back.model_dump_json(indent=2) == text
    assert back.schema_version == "1.1"
    assert BeatsFile(sha256=SHA, tracker="librosa").beats == []


@pytest.mark.parametrize("tracker", ["aubio", "", "Madmom"])
def test_beats_file_tracker_is_madmom_or_librosa(tracker):
    with pytest.raises(ValidationError, match="tracker"):
        BeatsFile(sha256=SHA, tracker=tracker)


def test_single_beat_round_trip():
    beat = Beat(time_ms=0.0, raw_time_ms=0.0, residual_ms=-0.75, bar=0, beat_in_bar=1, is_downbeat=True)
    assert Beat.model_validate_json(beat.model_dump_json()) == beat


# --- committed json schema ---


def test_committed_schema_matches_the_model():
    committed = SCHEMA_PATH.read_text(encoding="utf-8")

    assert render_schema() == committed, (
        "shared/schema/timing_report.schema.json is out of date, run python -m backend.schema.export_schema"
    )


def test_committed_beats_schema_matches_the_model():
    committed = BEATS_SCHEMA_PATH.read_text(encoding="utf-8")

    assert render_schema(BeatsFile) == committed, (
        "shared/schema/beats.schema.json is out of date, run python -m backend.schema.export_schema"
    )


def test_export_schema_check_passes(capsys):
    assert main(["--check"]) == 0
    assert "up to date" in capsys.readouterr().out


# --- validation rules ---


def test_valid_payload_is_actually_valid():
    # the rule tests below break one thing at a time, so the base has to be clean
    assert TimingReport.model_validate(valid_payload()) == full_report()


@pytest.mark.parametrize(
    "path",
    [(), ("source",), ("trim",), ("tempo_map", 0), ("meter_map", 0), ("sections", 0), ("edits", 0)],
    ids=["top-level", "source", "trim", "tempo-segment", "meter-segment", "section", "edit"],
)
def test_unknown_field_is_rejected(path):
    payload = valid_payload()
    node = payload
    for key in path:
        node = node[key]
    node["colour"] = "teal"

    with pytest.raises(ValidationError, match="colour"):
        TimingReport.model_validate(payload)


@pytest.mark.parametrize("container", ["tempo_map", "meter_map", "sections"])
@pytest.mark.parametrize("bad", ["semi", "AUTO", ""], ids=["semi", "uppercase", "empty"])
def test_segment_source_must_be_auto_or_manual(container, bad):
    payload = valid_payload()
    payload[container][0]["source"] = bad

    with pytest.raises(ValidationError, match="source"):
        TimingReport.model_validate(payload)


@pytest.mark.parametrize("source", ["auto", "manual"])
def test_segment_source_accepts_both_values(source):
    payload = valid_payload()
    for container in ("tempo_map", "meter_map", "sections"):
        payload[container][0]["source"] = source

    report = TimingReport.model_validate(payload)

    assert report.tempo_map[0].source == source


def test_trim_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="before start_ms"):
        Trim(start_ms=5000.0, end_ms=1000.0)

    payload = valid_payload()
    payload["trim"] = {"start_ms": 5000.0, "end_ms": 1000.0}
    with pytest.raises(ValidationError, match="before start_ms"):
        TimingReport.model_validate(payload)


def test_section_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="before start_ms"):
        Section(label="x", start_ms=5000.0, end_ms=1000.0, source="manual")


@pytest.mark.parametrize("denominator", [3, 5, 6, 12, 0, -4], ids=lambda d: f"den{d}")
def test_meter_denominator_must_be_a_power_of_two(denominator):
    with pytest.raises(ValidationError):
        MeterSegment(start_bar=0, numerator=4, denominator=denominator, source="auto")


@pytest.mark.parametrize("denominator", [1, 2, 4, 8, 16, 32], ids=lambda d: f"den{d}")
def test_meter_denominator_accepts_powers_of_two(denominator):
    segment = MeterSegment(start_bar=0, numerator=4, denominator=denominator, source="auto")
    assert segment.denominator == denominator


@pytest.mark.parametrize(
    "sha",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", "a" * 64 + "\n", " " + "a" * 63],
    ids=["too-short", "too-long", "uppercase", "not-hex", "empty", "trailing-newline", "leading-space"],
)
def test_bad_sha256_is_rejected(sha):
    payload = valid_payload()
    payload["source"]["sha256"] = sha
    with pytest.raises(ValidationError, match="sha256"):
        TimingReport.model_validate(payload)

    # same pattern on the beats file
    with pytest.raises(ValidationError, match="sha256"):
        BeatsFile(sha256=sha)


@pytest.mark.parametrize(
    "stamp",
    ["2026-03-01T12:30:15", "2026-03-01 12:30:15.123456"],
    ids=["iso-no-offset", "space-separated"],
)
def test_naive_edit_timestamp_is_rejected_from_json(stamp):
    payload = valid_payload()
    payload["edits"][0]["timestamp"] = stamp

    with pytest.raises(ValidationError, match="timezone"):
        TimingReport.model_validate(payload)


def test_naive_edit_timestamp_is_rejected_from_python():
    with pytest.raises(ValidationError, match="timezone"):
        Edit(field="trim/start_ms", old=1.0, new=2.0, timestamp=datetime(2026, 3, 1, 12, 30, 15))


def test_aware_timestamp_with_z_suffix_is_accepted():
    payload = valid_payload()
    payload["edits"][0]["timestamp"] = "2026-03-01T12:30:15Z"

    report = TimingReport.model_validate(payload)

    assert report.edits[0].timestamp.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "change",
    [
        ("schema_version", "2.0"),
        # 1.0 reports have no codec or padding, they don't load as 1.1
        ("schema_version", "1.0"),
        ("source/decoder_padding_samples", -1),
        ("tempo_map/0/bpm", 0),
        ("tempo_map/0/bpm", -120.0),
        ("tempo_map/0/confidence", 1.5),
        ("tempo_map/0/start_ms", -1.0),
        ("source/sample_rate", 0),
        ("source/duration_ms", -1.0),
        ("meter_map/0/numerator", 0),
        ("meter_map/0/start_bar", -1),
    ],
    ids=lambda c: f"{c[0]}={c[1]}",
)
def test_out_of_range_values_are_rejected(change):
    path, value = change
    *parents, leaf = path.split("/")
    payload = valid_payload()
    node = payload
    for key in parents:
        node = node[int(key)] if key.isdigit() else node[key]
    node[leaf] = value

    with pytest.raises(ValidationError):
        TimingReport.model_validate(payload)


@pytest.mark.parametrize(
    "beat",
    [
        {"time_ms": -1.0, "raw_time_ms": 0.0, "residual_ms": 0.0, "bar": 0, "beat_in_bar": 1, "is_downbeat": True},
        {"time_ms": 0.0, "raw_time_ms": -1.0, "residual_ms": 0.0, "bar": 0, "beat_in_bar": 1, "is_downbeat": True},
        {"time_ms": 0.0, "raw_time_ms": 0.0, "residual_ms": 0.0, "bar": -1, "beat_in_bar": 1, "is_downbeat": True},
        # beats inside a bar are 1-based
        {"time_ms": 0.0, "raw_time_ms": 0.0, "residual_ms": 0.0, "bar": 0, "beat_in_bar": 0, "is_downbeat": True},
        {"time_ms": 0.0, "raw_time_ms": 0.0, "bar": 0, "beat_in_bar": 1, "is_downbeat": True},
        {"time_ms": 0.0, "raw_time_ms": 0.0, "residual_ms": 0.0, "bar": 0, "beat_in_bar": 1, "is_downbeat": True, "extra": 1},
    ],
    ids=["negative-time", "negative-raw-time", "negative-bar", "zero-beat-in-bar", "missing-residual", "unknown-field"],
)
def test_bad_beat_is_rejected(beat):
    with pytest.raises(ValidationError):
        Beat.model_validate(beat)
