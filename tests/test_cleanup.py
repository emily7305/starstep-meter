"""Retention at startup, deleting one job by hand, and queued jobs picked up again after a restart."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.models import JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import AudioSource, BeatsFile, Edit, TempoSegment, TimingReport, Trim
from tests.synth import ClickTrackSpec, cached_click_wav

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
RETENTION = timedelta(days=14)
POLL_TIMEOUT_S = 60.0


def stamp(when: datetime) -> str:
    return when.isoformat(timespec="milliseconds")


def write_job_dir(
    jobs_dir: Path,
    created: datetime,
    status: str = "done",
    updated: datetime | None = None,
    edited: datetime | None = None,
    original: bytes | None = b"RIFF",
) -> str:
    # by hand, so the dates are whatever the test says and not the clock's
    job_id = uuid.uuid4().hex
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True)
    job = {"job_id": job_id, "filename": "song.wav", "sha256": "0" * 64, "size_bytes": 4, "created_at": stamp(created)}
    # a running job is somewhere in the pipeline, the other states are their own stage
    stage = "beats" if status == "running" else status
    state = {"status": status, "stage": stage, "error": None, "updated_at": stamp(updated or created)}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    if original is not None:
        (job_dir / "original.wav").write_bytes(original)
    if status == "done":
        (job_dir / "decoded.wav").write_bytes(b"RIFF-decoded")
        edits = [] if edited is None else [Edit(field="tempo_map/0/anchor_ms", old=2000.0, new=2001.0, timestamp=edited)]
        (job_dir / "report.json").write_text(make_report(edits).model_dump_json(), encoding="utf-8")
    return job_id


def make_report(edits: list[Edit] | None = None) -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename="song.wav", sha256="0" * 64, duration_ms=22000.0, sample_rate=44100, codec="pcm_f32le", decoder_padding_samples=0
        ),
        trim=Trim(start_ms=2000.0, end_ms=21500.0),
        tempo_map=[TempoSegment(start_ms=2000.0, end_ms=21500.0, bpm=120.0, anchor_ms=2000.0, confidence=1.0, source="auto")],
        edits=edits or [],
    )


def wait_done(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, body
        time.sleep(0.05)


# --- retention ---


def test_remove_expired_takes_only_jobs_unchanged_past_the_retention(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    old = write_job_dir(store.jobs_dir, NOW - timedelta(days=30))
    recent = write_job_dir(store.jobs_dir, NOW - timedelta(days=2))
    # uploaded long ago, edited last week, still in use
    edited = write_job_dir(store.jobs_dir, NOW - timedelta(days=30), edited=NOW - timedelta(days=3))
    # re-analysed last week
    rerun = write_job_dir(store.jobs_dir, NOW - timedelta(days=30), updated=NOW - timedelta(days=5))
    # exactly at the edge is still inside
    edge = write_job_dir(store.jobs_dir, NOW - RETENTION)
    failed = write_job_dir(store.jobs_dir, NOW - timedelta(days=20), status="failed")

    removed = store.remove_expired(NOW, RETENTION)

    assert sorted(removed) == sorted([old, failed])
    assert store.job_ids() == sorted([recent, edited, rerun, edge])


def test_an_unfinished_upload_goes_by_its_folder_time(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    stale = store.jobs_dir / uuid.uuid4().hex
    fresh = store.jobs_dir / uuid.uuid4().hex
    for folder in (stale, fresh):
        folder.mkdir(parents=True)
        (folder / "original.wav").write_bytes(b"RIF")
    month_ago = (NOW - timedelta(days=30)).timestamp()
    os.utime(stale, (month_ago, month_ago))
    os.utime(fresh, (NOW.timestamp(), NOW.timestamp()))

    assert store.remove_expired(NOW, RETENTION) == [stale.name]
    assert store.job_ids() == [fresh.name]


def test_startup_deletes_expired_jobs_with_their_decoded_audio(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    now = datetime.now(timezone.utc)
    old = write_job_dir(settings.jobs_dir, now - timedelta(days=15))
    kept = write_job_dir(settings.jobs_dir, now - timedelta(days=13))

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/jobs/{old}").status_code == 404
        assert client.get(f"/api/jobs/{kept}/report").status_code == 200
    assert not (settings.jobs_dir / old).exists()
    assert (settings.jobs_dir / kept / "decoded.wav").is_file()


def test_retention_0_keeps_everything(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", retention_days=0)
    ancient = write_job_dir(settings.jobs_dir, datetime(2025, 1, 1, tzinfo=timezone.utc))

    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/jobs/{ancient}").json()["status"] == "done"


def test_retention_comes_from_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().retention_days == 14
    monkeypatch.setenv("STARSTEP_RETENTION_DAYS", "30")
    assert Settings.from_env().retention_days == 30
    monkeypatch.setenv("STARSTEP_RETENTION_DAYS", "-1")
    with pytest.raises(ValueError, match="retention_days"):
        Settings.from_env()


# --- DELETE /api/jobs/{id} ---


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


def test_delete_removes_the_whole_job(client: TestClient, settings: Settings) -> None:
    job_id = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc))
    other = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc))

    resp = client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 204
    assert resp.content == b""
    assert not (settings.jobs_dir / job_id).exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert [j["job_id"] for j in client.get("/api/jobs").json()] == [other]


def test_delete_an_unfinished_upload(client: TestClient, settings: Settings) -> None:
    folder = settings.jobs_dir / uuid.uuid4().hex
    folder.mkdir(parents=True)
    (folder / "original.wav").write_bytes(b"RIF")

    assert client.delete(f"/api/jobs/{folder.name}").status_code == 204
    assert not folder.exists()


@pytest.mark.parametrize(("status", "stage"), [("queued", "queued"), ("running", "beats")])
def test_delete_waits_for_a_job_that_is_still_going(client: TestClient, settings: Settings, status: str, stage: str) -> None:
    job_id = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc))
    # written after startup, so nothing picks it up
    JobStore(settings.jobs_dir).write_status(job_id, JobStatus(status=status, stage=stage))

    resp = client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 409
    assert resp.json()["detail"] == f"job is still at {stage}, wait for it to finish"
    assert (settings.jobs_dir / job_id / "status.json").is_file()


@pytest.mark.parametrize("job_id", ["0" * 32, "not-a-job-id"])
def test_delete_of_an_unknown_job_is_404(client: TestClient, job_id: str) -> None:
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


# --- queued jobs after a restart ---


def fake_analysis(original_path, work_dir, filename, sha256, on_stage=None, config=None, previous=None):
    for stage in ("decode", "trim", "beats", "snap", "tempo", "meter", "check"):
        on_stage(stage)
    (Path(work_dir) / "decoded.wav").write_bytes(b"RIFF-decoded")
    report = make_report().model_copy(update={"source": make_report().source.model_copy(update={"filename": filename})})
    return SimpleNamespace(report=report, beats=BeatsFile(sha256=sha256, tracker="madmom", octave="kept"))


def test_a_queued_job_is_run_after_a_restart(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.api.jobs.run_analysis", fake_analysis)
    # what a job folder looks like when the server stopped before the worker got to it
    job_id = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc), status="queued")

    with TestClient(create_app(settings)) as client:
        body = wait_done(client, job_id)
        assert body == {"status": "done", "stage": "done", "error": None, "report_available": False}
        assert client.get(f"/api/jobs/{job_id}/report").json()["source"]["filename"] == "song.wav"


def test_a_running_job_is_still_marked_failed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.api.jobs.run_analysis", fake_analysis)
    job_id = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc), status="running")

    with TestClient(create_app(settings)) as client:
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "failed"
        assert body["error"] == {"stage": "beats", "message": "server restarted before the job finished"}


@pytest.mark.ffmpeg
def test_a_queued_click_track_finishes_after_a_restart(settings: Settings) -> None:
    path, track = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0))
    job_id = write_job_dir(settings.jobs_dir, datetime.now(timezone.utc), status="queued", original=None)
    shutil.copyfile(path, settings.jobs_dir / job_id / "original.wav")

    with TestClient(create_app(settings)) as client:
        body = wait_done(client, job_id)
        assert body["status"] == "done", body
        report = client.get(f"/api/jobs/{job_id}/report").json()
    assert abs(report["tempo_map"][0]["bpm"] - 120.0) <= 0.01
    assert abs(report["trim"]["start_ms"] - track.content_start_ms) <= 10
