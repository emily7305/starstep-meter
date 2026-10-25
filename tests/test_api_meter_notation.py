"""Tests for the meter and notation suggestion edits on PATCH /report, jobs are built by hand so only one test needs ffmpeg."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.analysis.bars import beat_lines
from backend.api.app import create_app
from backend.api.settings import Settings
from backend.schema.models import (
    AudioSource,
    Beat,
    BeatsFile,
    MeterSegment,
    NotationKind,
    NotationSuggestion,
    SegmentSource,
    TempoSegment,
    TimingReport,
    Trim,
)
from tests.synth import DrumTrackSpec, cached_drum_wav

POLL_TIMEOUT_S = 180.0
LINE_TOLERANCE_MS = 0.01
BOUNDARY_TOLERANCE_MS = 0.001
CREATED_AT = "2026-01-01T00:00:00.000+00:00"
# 240 bpm, a beat is 250 ms and a 4/4 bar is a second
BPM = 240.0
BEAT_MS = 250.0
START_MS = 2000.0
END_MS = 62000.0


def bar(k: int) -> float:
    return START_MS + 4 * BEAT_MS * k


HALF_SPAN = (bar(10), bar(20))
DOUBLE_SPAN = (bar(30), bar(40))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # the hand-built jobs carry fixed dates from early 2026, retention would delete them at startup
    return Settings(data_dir=tmp_path / "data", retention_days=0)


@pytest.fixture
def client(settings: Settings):
    # as a context manager so the lifespan (recover / shutdown) actually runs
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed", exc_type=ImportError)


def upload(client: TestClient, name: str, data: bytes):
    return client.post("/api/jobs", files={"file": (name, data, "application/octet-stream")})


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job still not finished after {POLL_TIMEOUT_S:.0f}s: {body}"
        time.sleep(0.2)


def wait_for_done(client: TestClient, job_id: str) -> None:
    body = wait_for_job(client, job_id)
    assert body["status"] == "done", body


def make_meter(
    start_ms: float = START_MS,
    end_ms: float = END_MS,
    numerator: int = 4,
    denominator: int = 4,
    confidence: float | None = 0.9,
    source: SegmentSource = "auto",
) -> MeterSegment:
    return MeterSegment(
        start_ms=start_ms, end_ms=end_ms, numerator=numerator, denominator=denominator, confidence=confidence, source=source
    )


def make_suggestion(kind: NotationKind, span: tuple[float, float]) -> NotationSuggestion:
    factor = 0.5 if kind == "half" else 2.0
    return NotationSuggestion(
        start_ms=span[0], end_ms=span[1], kind=kind, suggested_bpm=BPM * factor, grid_bpm=BPM, score=0.8
    )


def make_report(meter_map: list[MeterSegment] | None = None) -> TimingReport:
    # none is the usual one 4/4 segment, an empty list is a report upgraded from 2.2
    if meter_map is None:
        meter_map = [make_meter()]
    return TimingReport(
        source=AudioSource(
            filename="song.mp3",
            sha256="0" * 64,
            duration_ms=64000.0,
            sample_rate=44100,
            codec="pcm_f32le",
            decoder_padding_samples=0,
        ),
        trim=Trim(start_ms=START_MS, end_ms=END_MS),
        tempo_map=[TempoSegment(start_ms=START_MS, end_ms=END_MS, bpm=BPM, anchor_ms=START_MS, confidence=1.0, source="auto")],
        meter_map=meter_map,
        notation_suggestions=[make_suggestion("half", HALF_SPAN), make_suggestion("double", DOUBLE_SPAN)],
    )


def make_beats() -> BeatsFile:
    beats = [
        Beat(
            time_ms=START_MS + BEAT_MS * i,
            raw_time_ms=START_MS + BEAT_MS * i,
            residual_ms=0.0,
            bar=i // 4,
            beat_in_bar=i % 4 + 1,
            is_downbeat=i % 4 == 0,
        )
        for i in range(int((END_MS - START_MS) / BEAT_MS))
    ]
    return BeatsFile(sha256="0" * 64, tracker="madmom", octave="kept", beats=beats)


def write_done_job(settings: Settings, report: TimingReport) -> str:
    # by hand on purpose, so these don't depend on the storage code that reads them back
    job_id = uuid.uuid4().hex
    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True)
    job = {"job_id": job_id, "filename": "song.mp3", "sha256": "0" * 64, "size_bytes": 1, "created_at": CREATED_AT}
    state = {"status": "done", "stage": "done", "error": None, "updated_at": "2026-01-01T00:00:00.000+00:00"}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    (job_dir / "report.json").write_text(report.model_dump_json(), encoding="utf-8")
    (job_dir / "beats.json").write_text(make_beats().model_dump_json(), encoding="utf-8")
    return job_id


def patch_edit(client: TestClient, job_id: str, body: dict):
    return client.patch(f"/api/jobs/{job_id}/report", json=body)


def stored_report(settings: Settings, job_id: str) -> TimingReport:
    text = (settings.jobs_dir / job_id / "report.json").read_text(encoding="utf-8")
    return TimingReport.model_validate_json(text)


def dump(segments: list) -> list[dict]:
    return [s.model_dump(mode="json") for s in segments]


def logged(edits: list[dict]) -> list[tuple]:
    return [(e["field"], e["old"], e["new"]) for e in edits]


def snapshot(root: Path) -> dict[str, bytes | None]:
    # folders count too, so a stray temp file or a new job dir shows up
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in sorted(root.rglob("*"))}


def grid_lines(tempo_map: list[dict]) -> np.ndarray:
    return np.array(beat_lines([TempoSegment.model_validate(s) for s in tempo_map]))


# --- set_meter ---


def test_set_meter_makes_the_segment_manual_and_logs_one_entry(client: TestClient, settings: Settings) -> None:
    original = make_report()
    job_id = write_done_job(settings, original)

    resp = patch_edit(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 6, "denominator": 8})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    segment = body["meter_map"][0]
    assert (segment["numerator"], segment["denominator"], segment["source"], segment["confidence"]) == (6, 8, "manual", None)
    (edit,) = body["edits"]
    assert edit["field"] == "meter_map/0"
    assert edit["old"] == {"numerator": 4, "denominator": 4, "confidence": 0.9, "source": "auto"}
    assert edit["new"] == {"numerator": 6, "denominator": 8, "confidence": None, "source": "manual"}

    # only the meter segment and the edit log move
    expected = original.model_copy(
        update={"meter_map": [make_meter(numerator=6, denominator=8, confidence=None, source="manual")]}
    )
    assert TimingReport.model_validate(body).model_copy(update={"edits": []}) == expected
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


def test_set_meter_on_a_report_without_a_meter_map_logs_the_whole_map(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report(meter_map=[]))

    resp = patch_edit(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    new_map = dump([make_meter(numerator=3, denominator=4, confidence=None, source="manual")])
    assert body["meter_map"] == new_map
    assert logged(body["edits"]) == [("meter_map", [], new_map)]
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


# --- split_meter and merge_meter ---


def test_split_meter_lands_on_the_nearest_beat_and_merge_meter_joins_it_again(client: TestClient, settings: Settings) -> None:
    original = make_report()
    job_id = write_done_job(settings, original)
    beat = START_MS + 41 * BEAT_MS

    # 0.3 of a beat is closer to the beat before than to the next one
    resp = patch_edit(client, job_id, {"op": "split_meter", "at_ms": beat + 0.3 * BEAT_MS})
    assert resp.status_code == 200, resp.text
    split = resp.json()
    left, right = split["meter_map"]
    assert left["end_ms"] == pytest.approx(beat, abs=BOUNDARY_TOLERANCE_MS)
    assert right["start_ms"] == left["end_ms"]
    assert (left["start_ms"], right["end_ms"]) == (START_MS, END_MS)
    assert [(m["numerator"], m["denominator"], m["source"]) for m in split["meter_map"]] == [(4, 4, "manual")] * 2
    assert logged(split["edits"]) == [("meter_map", dump(original.meter_map), split["meter_map"])]

    resp = patch_edit(client, job_id, {"op": "merge_meter", "segment": 0})
    assert resp.status_code == 200, resp.text
    merged = resp.json()
    (segment,) = merged["meter_map"]
    assert (segment["start_ms"], segment["end_ms"], segment["source"]) == (START_MS, END_MS, "manual")
    assert logged(merged["edits"]) == [*logged(split["edits"]), ("meter_map", split["meter_map"], merged["meter_map"])]
    assert stored_report(settings, job_id) == TimingReport.model_validate(merged)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 3}, id="denominator 3"),
        pytest.param({"op": "set_meter", "segment": 0, "numerator": 0, "denominator": 4}, id="numerator 0"),
        pytest.param({"op": "set_meter", "segment": 0, "numerator": 33, "denominator": 4}, id="numerator 33"),
        pytest.param({"op": "set_meter", "segment": 2, "numerator": 3, "denominator": 4}, id="set_meter past the end"),
        pytest.param({"op": "merge_meter", "segment": 2}, id="merge_meter past the end"),
        pytest.param({"op": "merge_meter", "segment": 1}, id="merge_meter on the last segment"),
        pytest.param({"op": "split_meter", "at_ms": START_MS}, id="split_meter at the start"),
        pytest.param({"op": "split_meter", "at_ms": END_MS}, id="split_meter at the end"),
        pytest.param({"op": "split_meter", "at_ms": bar(20)}, id="split_meter at a boundary between segments"),
        pytest.param({"op": "split_meter", "at_ms": bar(20) + 0.3 * BEAT_MS}, id="split_meter near a boundary"),
    ],
)
def test_bad_meter_body_is_422_and_writes_nothing(client: TestClient, settings: Settings, body: dict) -> None:
    two = [make_meter(end_ms=bar(20)), make_meter(start_ms=bar(20), numerator=3)]
    job_id = write_done_job(settings, make_report(two))
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, body)
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


# --- apply_suggestion ---


def test_apply_suggestion_splits_the_tempo_map_and_marks_it_applied(client: TestClient, settings: Settings) -> None:
    original = make_report()
    job_id = write_done_job(settings, original)

    resp = patch_edit(client, job_id, {"op": "apply_suggestion", "suggestion": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tempo = body["tempo_map"]
    assert [(s["start_ms"], s["end_ms"]) for s in tempo] == [(START_MS, HALF_SPAN[0]), HALF_SPAN, (HALF_SPAN[1], END_MS)]
    assert [s["bpm"] for s in tempo] == [BPM, BPM / 2, BPM]
    assert [s["source"] for s in tempo] == ["manual"] * 3
    assert [s["status"] for s in body["notation_suggestions"]] == ["applied", "open"]
    # two places changed, so the one entry sits at the report itself
    assert logged(body["edits"]) == [
        (
            "",
            {"tempo_map": dump(original.tempo_map), "notation_suggestions/0/status": "open"},
            {"tempo_map": tempo, "notation_suggestions/0/status": "applied"},
        )
    ]

    # nothing moves, half drops every other line inside the span
    old_lines, new_lines = grid_lines(body["edits"][0]["old"]["tempo_map"]), grid_lines(tempo)
    assert all(np.abs(old_lines - t).min() <= LINE_TOLERANCE_MS for t in new_lines)
    assert len(old_lines) - len(new_lines) == (HALF_SPAN[1] - HALF_SPAN[0]) / BEAT_MS / 2

    assert body["meter_map"] == dump(original.meter_map)
    assert body["notation_suggestions"][1:] == dump(original.notation_suggestions[1:])
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


@pytest.mark.parametrize(("first", "state"), [("apply_suggestion", "applied"), ("dismiss_suggestion", "dismissed")])
def test_apply_suggestion_on_a_decided_suggestion_is_422_and_writes_nothing(
    client: TestClient, settings: Settings, first: str, state: str
) -> None:
    job_id = write_done_job(settings, make_report())
    assert patch_edit(client, job_id, {"op": first, "suggestion": 0}).status_code == 200
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, {"op": "apply_suggestion", "suggestion": 0})
    assert resp.status_code == 422, resp.text
    assert f"already {state}" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("op", ["apply_suggestion", "dismiss_suggestion"])
def test_suggestion_index_past_the_end_is_422_and_writes_nothing(client: TestClient, settings: Settings, op: str) -> None:
    job_id = write_done_job(settings, make_report())
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, {"op": op, "suggestion": 2})
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


def test_apply_suggestion_after_set_bpm_is_422_and_names_the_bpm(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report())
    assert patch_edit(client, job_id, {"op": "set_bpm", "segment": 0, "bpm": 180.0}).status_code == 200
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, {"op": "apply_suggestion", "suggestion": 0})
    assert resp.status_code == 422, resp.text
    assert "bpm" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


# --- dismiss_suggestion ---


def test_dismiss_suggestion_changes_only_the_status(client: TestClient, settings: Settings) -> None:
    original = make_report()
    job_id = write_done_job(settings, original)

    resp = patch_edit(client, job_id, {"op": "dismiss_suggestion", "suggestion": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert logged(body["edits"]) == [("notation_suggestions/1/status", "open", "dismissed")]

    first, second = original.notation_suggestions
    expected = original.model_copy(update={"notation_suggestions": [first, second.model_copy(update={"status": "dismissed"})]})
    assert TimingReport.model_validate(body).model_copy(update={"edits": []}) == expected
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


# --- through a real analysis and a re-analysis ---


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_dismissed_suggestion_and_manual_meter_survive_a_reanalysis(client: TestClient) -> None:
    path, _ = cached_drum_wav(DrumTrackSpec(bpm=130, sections=((16, 8, "half"), (32, 8, "double"))))
    resp = upload(client, "drums.wav", path.read_bytes())
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    wait_for_done(client, job_id)

    analysed = client.get(f"/api/jobs/{job_id}/report").json()
    assert [(s["kind"], s["status"]) for s in analysed["notation_suggestions"]] == [("half", "open"), ("double", "open")]

    resp = patch_edit(client, job_id, {"op": "dismiss_suggestion", "suggestion": 0})
    assert resp.status_code == 200, resp.text
    resp = patch_edit(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 4})
    assert resp.status_code == 200, resp.text
    edited = resp.json()
    dismissed, manual = edited["notation_suggestions"][0], edited["meter_map"][0]
    assert dismissed["status"] == "dismissed"
    assert (manual["numerator"], manual["denominator"], manual["source"]) == (3, 4, "manual")

    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 202, resp.text
    wait_for_done(client, job_id)

    again = client.get(f"/api/jobs/{job_id}/report").json()
    suggestions = again["notation_suggestions"]
    assert [s for s in suggestions if s["kind"] == "half"] == [dismissed]
    assert [s["status"] for s in suggestions if s["kind"] == "double"] == ["open"]
    assert again["meter_map"][0] == manual
    assert again["edits"] == edited["edits"]

    beats = client.get(f"/api/jobs/{job_id}/beats")
    assert beats.status_code == 200, beats.text
    assert beats.json()["grid_features"]


def test_applying_a_downbeat_shift_restarts_the_bars_there(client: TestClient, settings: Settings) -> None:
    # the tracker's bars restarted a beat into bar 12, the meter ran on through
    at = bar(12) + BEAT_MS
    shift = NotationSuggestion(start_ms=at, end_ms=END_MS, kind="shift", suggested_bpm=BPM, grid_bpm=BPM, score=1.0)
    original = make_report().model_copy(update={"notation_suggestions": [shift]})
    job_id = write_done_job(settings, original)

    resp = patch_edit(client, job_id, {"op": "apply_suggestion", "suggestion": 0})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # the tempo map stays, the meter splits there and the bars start over on that beat
    assert body["tempo_map"] == dump(original.tempo_map)
    assert [(m["start_ms"], m["end_ms"], m["numerator"]) for m in body["meter_map"]] == [(START_MS, at, 4), (at, END_MS, 4)]
    assert logged(body["edits"]) == [
        (
            "",
            {"meter_map": dump(original.meter_map), "notation_suggestions/0/status": "open"},
            {"meter_map": body["meter_map"], "notation_suggestions/0/status": "applied"},
        )
    ]
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)
