"""Re-analysis: it runs every stage again, replaces the auto results, and moves the job up the recent list."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.settings import Settings
from backend.api.storage import JobStore
from tests.synth import ClickTrackSpec, cached_click_wav
from tests.test_reanalysis_failure import fails_at, fake_analysis, reanalyze, succeeds, wait_for_job, write_job

EVERY_STAGE = ["queued", "decode", "trim", "beats", "snap", "tempo", "meter", "check", "done"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # the hand-built jobs carry fixed dates from early 2026, retention would delete them at startup
    return Settings(data_dir=tmp_path / "data", retention_days=0)


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


def _set_created(settings: Settings, job_id: str, created_at: str) -> None:
    path = settings.jobs_dir / job_id / "job.json"
    job = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**job, "created_at": created_at}), encoding="utf-8")


def test_a_reanalyzed_job_moves_to_the_top_and_says_when(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    older = write_job(settings, "done", "done")
    newer = write_job(settings, "done", "done")
    _set_created(settings, older, "2026-01-01T00:00:00.000+00:00")
    _set_created(settings, newer, "2026-02-01T00:00:00.000+00:00")
    before = client.get("/api/jobs").json()
    assert [j["job_id"] for j in before] == [newer, older]
    assert [j["reanalyzed_at"] for j in before] == [None, None]

    fake_analysis(monkeypatch, succeeds)
    assert reanalyze(client, older)["status"] == "done"

    after = client.get("/api/jobs").json()
    assert [j["job_id"] for j in after] == [older, newer]
    # the upload date stays, the re-analysis is its own field
    assert after[0]["created_at"] == "2026-01-01T00:00:00.000+00:00"
    assert datetime.fromisoformat(after[0]["reanalyzed_at"]) > datetime.fromisoformat(after[1]["created_at"])


def test_a_failed_reanalysis_doesnt_move_the_job(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    older = write_job(settings, "done", "done")
    newer = write_job(settings, "done", "done")
    _set_created(settings, older, "2026-01-01T00:00:00.000+00:00")
    _set_created(settings, newer, "2026-02-01T00:00:00.000+00:00")
    fake_analysis(monkeypatch, fails_at("beats"))
    assert reanalyze(client, older)["status"] == "failed"

    after = client.get("/api/jobs").json()
    assert [j["job_id"] for j in after] == [newer, older]
    assert after[1]["reanalyzed_at"] is None


@pytest.mark.ffmpeg
def test_reanalysis_runs_every_stage_and_replaces_every_auto_result(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a tempo change, so one segment can be set by hand while the other stays auto
    spec = ClickTrackSpec(bpm=120, beats=64, lead_silence_s=1.0, accent_downbeats=True, tempo_changes=((32, 150.0),))
    path, _ = cached_click_wav(spec)
    job_id = client.post("/api/jobs", files={"file": ("change.wav", path.read_bytes(), "application/octet-stream")}).json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "done"
    first = client.get(f"/api/jobs/{job_id}/report").json()
    assert len(first["tempo_map"]) == 2
    resp = client.patch(f"/api/jobs/{job_id}/report", json={"op": "set_bpm", "segment": 1, "bpm": 300.0})
    assert resp.status_code == 200, resp.text
    edited = resp.json()

    # every auto result changed on disk by hand. a stage the re-analysis skipped would leave its part
    job_dir = settings.jobs_dir / job_id
    report = json.loads((job_dir / "report.json").read_text(encoding="utf-8"))
    report["tempo_map"][0].update(bpm=99.0, anchor_ms=report["tempo_map"][0]["anchor_ms"] + 7.0, confidence=0.01)
    for m in report["meter_map"]:
        m["numerator"] = 3
    report["offbeat_runs"] = [{"start_ms": 2000.0, "end_ms": 4000.0, "beats": 9}]
    report["subdivision_sections"] = [
        {"start_ms": 2000.0, "end_ms": 6000.0, "kind": "swing", "ratio": 2.0, "division": 12, "grid_bpm": 120.0, "score": 0.9}
    ]
    for span in report["confidence_spans"]:
        span.update(confidence=0.0, low=True)
    report["cross_check"]["segments"][0]["disagreement_ms"] = 99.0
    (job_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    beats = json.loads((job_dir / "beats.json").read_text(encoding="utf-8"))
    beats_count = len(beats["beats"])
    beats["beats"] = beats["beats"][:4]
    (job_dir / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
    decoded = (job_dir / "decoded.wav").read_bytes()
    (job_dir / "decoded.wav").write_bytes(b"RIFF-not-the-decode")

    # every status the runner writes, polling could miss a fast stage
    seen: list[str] = []
    write_status = JobStore.write_status

    def record(self: JobStore, job: str, status) -> None:
        seen.append(status.stage)
        write_status(self, job, status)

    monkeypatch.setattr(JobStore, "write_status", record)
    assert reanalyze(client, job_id)["status"] == "done"

    assert seen == EVERY_STAGE
    again = client.get(f"/api/jobs/{job_id}/report").json()
    # the auto segment and every other analysis result are the analysis' again
    assert again["tempo_map"][0] == first["tempo_map"][0]
    assert again["meter_map"] == first["meter_map"]
    assert again["offbeat_runs"] == first["offbeat_runs"] == []
    assert again["subdivision_sections"] == first["subdivision_sections"] == []
    assert again["cross_check"] == first["cross_check"]
    manual_from = again["tempo_map"][1]["start_ms"]
    assert again["confidence_spans"] == [s for s in first["confidence_spans"] if (s["start_ms"] + s["end_ms"]) / 2 < manual_from]
    # the manual segment and the edit log stay
    assert again["tempo_map"][1] == edited["tempo_map"][1]
    assert again["edits"] == edited["edits"]
    assert len(client.get(f"/api/jobs/{job_id}/beats").json()["beats"]) == beats_count
    assert (job_dir / "decoded.wav").read_bytes() == decoded
    assert client.get("/api/jobs").json()[0]["reanalyzed_at"] is not None
