"""API tests through FastAPI's TestClient, every app gets its own throwaway data dir."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.api.__main__ import is_loopback
from backend.api.app import create_app
from backend.api.jobs import JobRunner
from backend.api.models import JobError
from backend.api.settings import Settings
from backend.api.storage import JobNotFoundError, JobStore
from backend.schema.models import TimingReport
from tests.synth import ClickTrackSpec, cached_click_wav

POLL_TIMEOUT_S = 60.0
STAGE_ORDER = ["queued", "decode", "trim", "beats", "snap", "tempo", "done"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings):
    # as a context manager so the lifespan (recover / shutdown) actually runs
    with TestClient(create_app(settings)) as c:
        yield c


def upload(client: TestClient, name: str, data: bytes):
    return client.post("/api/jobs", files={"file": (name, data, "application/octet-stream")})


def job_dirs(settings: Settings) -> list[Path]:
    if not settings.jobs_dir.exists():
        return []
    return sorted(settings.jobs_dir.iterdir())


def wait_for_job(client: TestClient, job_id: str) -> tuple[dict, list[str]]:
    # returns the final status body and every distinct stage seen on the way
    deadline = time.monotonic() + POLL_TIMEOUT_S
    seen: list[str] = []
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if not seen or seen[-1] != body["stage"]:
            seen.append(body["stage"])
        if body["status"] in ("done", "failed"):
            return body, seen
        assert time.monotonic() < deadline, f"job still not finished after {POLL_TIMEOUT_S:.0f}s: {body}"
        time.sleep(0.05)


def is_subsequence(seen: list[str], order: list[str]) -> bool:
    # the poll can miss a fast stage, but it should never see them out of order
    remaining = iter(order)
    return all(stage in remaining for stage in seen)


def write_job_dir(settings: Settings, status: str, stage: str) -> str:
    # by hand on purpose, so these don't depend on the storage code that reads them back
    job_id = uuid.uuid4().hex
    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True)
    job = {
        "job_id": job_id,
        "filename": "song.mp3",
        "sha256": "0" * 64,
        "size_bytes": 1,
        "created_at": "2026-01-01T00:00:00.000+00:00",
    }
    state = {"status": status, "stage": stage, "error": None, "updated_at": "2026-01-01T00:00:00.000+00:00"}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    return job_id


def test_health(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    for key in ("ffmpeg", "ffprobe", "madmom"):
        assert isinstance(body[key], bool)


@pytest.mark.ffmpeg
def test_click_track_job_end_to_end(client: TestClient, settings: Settings) -> None:
    path, track = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0))
    data = path.read_bytes()

    resp = upload(client, "click 120.wav", data)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    assert len(job_id) == 32 and set(job_id) <= set("0123456789abcdef")

    body, seen = wait_for_job(client, job_id)
    assert body == {"status": "done", "stage": "done", "error": None}
    assert is_subsequence(seen, STAGE_ORDER), seen

    resp = client.get(f"/api/jobs/{job_id}/report")
    assert resp.status_code == 200, resp.text
    report = TimingReport.model_validate(resp.json())

    assert report.schema_version == "1.1"
    assert report.source.filename == "click 120.wav"
    assert report.source.codec == "pcm_f32le"
    assert report.source.decoder_padding_samples == 0
    assert report.source.sha256 == hashlib.sha256(data).hexdigest()
    assert report.source.sample_rate == 44100
    assert abs(report.trim.start_ms - track.content_start_ms) <= 10
    # unaccented clicks, so which click is beat 1 is up to the tracker, but it has to be a click
    assert report.beat_offset_ms is not None
    phase = (report.beat_offset_ms - track.content_start_ms + 250.0) % 500.0 - 250.0
    assert abs(phase) <= 5.0

    assert len(report.tempo_map) == 1
    segment = report.tempo_map[0]
    assert abs(segment.bpm - 120) <= 0.01
    assert segment.source == "auto"
    assert segment.confidence is not None and segment.confidence > 0
    assert segment.start_ms == report.trim.start_ms

    assert report.meter_map == []
    assert report.sections == []
    assert report.edits == []

    job_dir = settings.jobs_dir / job_id
    assert (job_dir / "status.json").is_file()
    assert (job_dir / "report.json").is_file()
    assert (job_dir / "beats.json").is_file()
    assert (job_dir / "job.json").is_file()
    assert TimingReport.model_validate_json((job_dir / "report.json").read_text(encoding="utf-8")) == report
    stored_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert stored_job["job_id"] == job_id
    assert stored_job["filename"] == "click 120.wav"
    assert stored_job["size_bytes"] == len(data)


def test_unsupported_extension_is_415(client: TestClient, settings: Settings) -> None:
    resp = upload(client, "notes.txt", b"just some text")
    assert resp.status_code == 415
    assert "unsupported file type" in resp.json()["detail"]
    assert job_dirs(settings) == []


@pytest.mark.ffmpeg
def test_fake_audio_is_415_and_leaves_nothing_behind(client: TestClient, settings: Settings) -> None:
    resp = upload(client, "song.mp3", b"definitely not audio")
    assert resp.status_code == 415
    assert resp.json()["detail"].startswith("not a readable audio file")
    assert job_dirs(settings) == []


@pytest.mark.parametrize(
    "size",
    [
        # well over the limit, turned away from content-length alone
        1_500_000,
        # just over, inside the multipart slack, so it's the byte count in ingest that catches it
        pytest.param(1024 * 1024 + 1024, marks=pytest.mark.ffmpeg),
    ],
)
def test_oversize_upload_is_413(tmp_path: Path, size: int) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_upload_mb=1)
    with TestClient(create_app(settings)) as client:
        resp = upload(client, "big.wav", b"\0" * size)
    assert resp.status_code == 413
    assert resp.json()["detail"] == "file is larger than the 1 MB limit"
    assert job_dirs(settings) == []


def test_missing_ffprobe_is_503_but_oversize_is_still_413(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data", max_upload_mb=1)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    with TestClient(create_app(settings)) as client:
        resp = upload(client, "song.wav", b"RIFF")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "ffprobe not found on PATH"
        # the size check runs before the route, so it doesn't care about ffprobe
        assert upload(client, "big.wav", b"\0" * 1_500_000).status_code == 413
    assert job_dirs(settings) == []


@pytest.mark.parametrize("how", ["no body", "wrong field name"])
def test_no_file_field_is_400(client: TestClient, settings: Settings, how: str) -> None:
    if how == "no body":
        resp = client.post("/api/jobs")
    else:
        resp = client.post("/api/jobs", files={"audio": ("song.wav", b"RIFF", "audio/wav")})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no file in the upload, expected a multipart field named file"
    assert job_dirs(settings) == []


@pytest.mark.parametrize(
    "job_id",
    [
        uuid.uuid4().hex,
        "not-a-job",
        # right length, but upper case isn't what uuid4().hex makes
        "A" * 32,
        "0" * 31,
    ],
)
def test_unknown_job_is_404_on_both_routes(client: TestClient, job_id: str) -> None:
    for suffix in ("", "/report"):
        resp = client.get(f"/api/jobs/{job_id}{suffix}")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "job not found"}


def test_store_never_builds_a_path_from_a_bad_id(settings: Settings) -> None:
    # http clients squash ".." before it gets here, so this is the only place it can be checked
    store = JobStore(settings.jobs_dir)
    for bad in ("..", "../outside", "", "A" * 32, "0" * 32 + "\n"):
        with pytest.raises(JobNotFoundError):
            store.job_dir(bad)
        assert store.read_status(bad) is None
    assert store.job_dir("0" * 32) == settings.jobs_dir / ("0" * 32)


def test_job_folder_without_status_is_not_a_job(client: TestClient, settings: Settings) -> None:
    # what a crash in the middle of an upload leaves behind
    job_id = uuid.uuid4().hex
    (settings.jobs_dir / job_id).mkdir(parents=True)
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_report_is_409_while_a_job_is_still_running(client: TestClient, settings: Settings) -> None:
    # written after startup, so recover() has already run and leaves it alone
    job_id = write_job_dir(settings, "running", "tempo")
    assert client.get(f"/api/jobs/{job_id}").json() == {"status": "running", "stage": "tempo", "error": None}
    resp = client.get(f"/api/jobs/{job_id}/report")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "report not ready, job is at tempo"


@pytest.mark.ffmpeg
def test_failed_job_keeps_its_stage(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    silent = tmp_path / "silent.wav"
    sf.write(silent, np.zeros(5 * 44100, dtype=np.float32), 44100)

    resp = upload(client, "silent.wav", silent.read_bytes())
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    body, seen = wait_for_job(client, job_id)
    assert body["status"] == "failed"
    assert body["stage"] == "failed"
    assert body["error"] == {"stage": "trim", "message": "audio is silent"}
    assert is_subsequence(seen, STAGE_ORDER + ["failed"]), seen

    resp = client.get(f"/api/jobs/{job_id}/report")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "job failed at trim: audio is silent"
    assert not (settings.jobs_dir / job_id / "report.json").exists()


@pytest.mark.ffmpeg
def test_restart_keeps_finished_jobs(settings: Settings) -> None:
    path, _ = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0))

    with TestClient(create_app(settings)) as first:
        job_id = upload(first, "click 120.wav", path.read_bytes()).json()["job_id"]
        body, _ = wait_for_job(first, job_id)
        assert body["status"] == "done"
        report_before = first.get(f"/api/jobs/{job_id}/report").json()

    with TestClient(create_app(settings)) as second:
        resp = second.get(f"/api/jobs/{job_id}")
        assert resp.json() == {"status": "done", "stage": "done", "error": None}
        resp = second.get(f"/api/jobs/{job_id}/report")
        assert resp.status_code == 200
        assert resp.json() == report_before


@pytest.mark.parametrize(
    ("status", "stage", "expected_stage"),
    [
        ("running", "decode", "decode"),
        ("running", "tempo", "tempo"),
        ("queued", "queued", "queued"),
    ],
)
def test_restart_fails_unfinished_jobs(settings: Settings, status: str, stage: str, expected_stage: str) -> None:
    job_id = write_job_dir(settings, status, stage)

    with TestClient(create_app(settings)) as client:
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "failed"
        assert body["stage"] == "failed"
        assert body["error"] == {"stage": expected_stage, "message": "server restarted before the job finished"}

        resp = client.get(f"/api/jobs/{job_id}/report")
        assert resp.status_code == 409
        assert resp.json()["detail"] == f"job failed at {expected_stage}: server restarted before the job finished"


def test_restart_leaves_a_bad_status_file_alone(settings: Settings) -> None:
    good = write_job_dir(settings, "running", "trim")
    bad = write_job_dir(settings, "running", "trim")
    (settings.jobs_dir / bad / "status.json").write_text("{not json", encoding="utf-8")

    # one unreadable job must not stop the server from coming up or from fixing the others
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/jobs/{good}").json()["status"] == "failed"
    assert (settings.jobs_dir / bad / "status.json").read_text(encoding="utf-8") == "{not json"


def test_unexpected_exception_is_recorded_at_the_last_stage(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JobStore(settings.jobs_dir)
    job_id, job_dir = store.create()
    (job_dir / "original.wav").write_bytes(b"x")
    store.write_job(job_id, "song.wav", "0" * 64, 1)

    def broken_analysis(original_path, work_dir, filename, sha256, on_stage=None, config=None):
        on_stage("decode")
        on_stage("trim")
        raise ValueError("boom")

    monkeypatch.setattr("backend.api.jobs.run_analysis", broken_analysis)
    runner = JobRunner(store, settings)
    try:
        runner.submit(job_id).result(timeout=10)
    finally:
        runner.shutdown()

    status = store.read_status(job_id)
    assert status is not None
    assert status.status == "failed"
    assert status.error == JobError(stage="trim", message="boom")


def test_settings_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STARSTEP_DATA_DIR", str(tmp_path / "somewhere"))
    monkeypatch.setenv("STARSTEP_MAX_UPLOAD_MB", "7")
    monkeypatch.setenv("STARSTEP_TRIM_THRESHOLD_DB", "-45.5")
    monkeypatch.setenv("STARSTEP_WORKERS", "2")
    settings = Settings.from_env()
    assert settings.data_dir == tmp_path / "somewhere"
    assert settings.jobs_dir == tmp_path / "somewhere" / "jobs"
    assert settings.max_upload_mb == 7
    assert settings.trim_threshold_db == -45.5
    assert settings.workers == 2

    monkeypatch.setenv("STARSTEP_WORKERS", "lots")
    with pytest.raises(ValueError, match="STARSTEP_WORKERS"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.20", False),
        ("my-laptop.local", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected
