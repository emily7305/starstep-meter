"""One manual change is one entry in edits, checked over a whole sequence through the api."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.models import JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import AudioSource, MeterSegment, RatioMergedSection, TempoSegment, TimingReport, Trim


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


def segment(start: float, end: float, **changes) -> TempoSegment:
    values = {"bpm": 120.0, "anchor_ms": 2000.0, "confidence": 1.0, "source": "auto"} | changes
    return TempoSegment(start_ms=start, end_ms=end, **values)


def write_job(settings: Settings, tempo: list[TempoSegment]) -> str:
    report = TimingReport(
        source=AudioSource(
            filename="song.wav", sha256="0" * 64, duration_ms=22000.0, sample_rate=44100, codec="pcm_f32le", decoder_padding_samples=0
        ),
        trim=Trim(start_ms=2000.0, end_ms=21500.0),
        tempo_map=tempo,
        meter_map=[MeterSegment(start_ms=2000.0, end_ms=21500.0, numerator=4, denominator=4, confidence=0.9, source="auto")],
    )
    store = JobStore(settings.jobs_dir)
    job_id, job_dir = store.create()
    (job_dir / "original.wav").write_bytes(b"RIFF")
    store.write_job(job_id, "song.wav", "0" * 64, 4)
    store.write_report(job_id, report)
    store.write_status(job_id, JobStatus(status="done", stage="done"))
    return job_id


def patch(client: TestClient, job_id: str, body: dict) -> dict:
    resp = client.patch(f"/api/jobs/{job_id}/report", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_offset_split_bpm_and_meter_give_one_entry_each(client: TestClient, settings: Settings) -> None:
    job_id = write_job(settings, [segment(2000.0, 21500.0)])
    first = segment(2000.0, 21500.0, anchor_ms=2003.0, confidence=None, source="manual").model_dump(mode="json")
    left = segment(2000.0, 10000.0, anchor_ms=2003.0, confidence=None, source="manual").model_dump(mode="json")
    # a split of a hand-set segment keeps its grid, the right side starts on its first line from the split
    right = segment(10000.0, 21500.0, anchor_ms=10003.0, confidence=None, source="manual").model_dump(mode="json")

    started = datetime.now(timezone.utc)
    patch(client, job_id, {"op": "set_anchor", "segment": 0, "anchor_ms": 2003.0})
    patch(client, job_id, {"op": "split", "at_ms": 10000.0})
    patch(client, job_id, {"op": "set_bpm", "segment": 1, "bpm": 240.0})
    report = patch(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 4})
    finished = datetime.now(timezone.utc)

    edits = report["edits"]
    assert [(e["field"], e["old"], e["new"]) for e in edits] == [
        # the first nudge of an auto segment also makes it manual and drops its confidence
        (
            "tempo_map/0",
            {"anchor_ms": 2000.0, "confidence": 1.0, "source": "auto"},
            {"anchor_ms": 2003.0, "confidence": None, "source": "manual"},
        ),
        ("tempo_map", [first], [left, right]),
        # already manual, so only the bpm moves
        ("tempo_map/1/bpm", 120.0, 240.0),
        (
            "meter_map/0",
            {"numerator": 4, "confidence": 0.9, "source": "auto"},
            {"numerator": 3, "confidence": None, "source": "manual"},
        ),
    ]
    for edit in edits:
        assert set(edit) == {"field", "old", "new", "timestamp"}
    stamps = [datetime.fromisoformat(e["timestamp"]) for e in edits]
    assert all(s.utcoffset() is not None for s in stamps)
    assert started <= stamps[0] <= stamps[1] <= stamps[2] <= stamps[3] <= finished


def test_a_meter_already_set_by_hand_logs_only_the_value_that_moved(client: TestClient, settings: Settings) -> None:
    job_id = write_job(settings, [segment(2000.0, 21500.0)])
    patch(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 7, "denominator": 4})

    patch(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 4})
    report = patch(client, job_id, {"op": "set_meter", "segment": 0, "numerator": 3, "denominator": 8})

    assert [(e["field"], e["old"], e["new"]) for e in report["edits"][1:]] == [
        ("meter_map/0/numerator", 7, 3),
        ("meter_map/0/denominator", 4, 8),
    ]


def test_an_edit_that_changes_nothing_adds_no_entry(client: TestClient, settings: Settings) -> None:
    job_id = write_job(settings, [segment(2000.0, 21500.0)])
    patch(client, job_id, {"op": "set_anchor", "segment": 0, "anchor_ms": 2003.0})

    report = patch(client, job_id, {"op": "set_anchor", "segment": 0, "anchor_ms": 2003.0})

    assert len(report["edits"]) == 1


def test_split_out_is_one_edit_for_both_cuts(client: TestClient, settings: Settings) -> None:
    felt = RatioMergedSection(start_ms=8000.0, end_ms=12000.0, bpm=90.0, ratio="3/4", fit=1.0)
    job_id = write_job(settings, [segment(2000.0, 21500.0, confidence=None, source="manual", ratio_merged=[felt])])

    report = patch(client, job_id, {"op": "split_out", "segment": 0, "section": 0})

    assert [(s["start_ms"], s["end_ms"]) for s in report["tempo_map"]] == [(2000.0, 8000.0), (8000.0, 12000.0), (12000.0, 21500.0)]
    assert len(report["edits"]) == 1
    edit = report["edits"][0]
    assert edit["field"] == "tempo_map"
    assert [(s["start_ms"], s["end_ms"]) for s in edit["old"]] == [(2000.0, 21500.0)]
    assert edit["new"] == report["tempo_map"]


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"op": "split_out", "segment": 0, "section": 1}, "segment 0 has no kept section 1, it has 0"),
        ({"op": "split_out", "segment": 3, "section": 0}, "no tempo segment 3, there are 1"),
    ],
)
def test_split_out_without_that_section_is_422(client: TestClient, settings: Settings, body: dict, detail: str) -> None:
    job_id = write_job(settings, [segment(2000.0, 21500.0)])

    resp = client.patch(f"/api/jobs/{job_id}/report", json=body)

    assert resp.status_code == 422
    assert resp.json()["detail"] == detail
    assert client.get(f"/api/jobs/{job_id}/report").json()["edits"] == []
