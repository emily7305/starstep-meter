"""A failed re-analysis keeps the last good report. Jobs are built by hand and run_analysis is faked."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.analysis.pipeline import StageError
from backend.api.app import create_app
from backend.api.jobs import JobRunner
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import AudioSource, Beat, BeatsFile, Edit, TempoSegment, TimingReport, Trim

POLL_TIMEOUT_S = 30.0
CREATED_AT = "2026-01-01T00:00:00.000+00:00"
RERUN = ".rerun"
STAGE_ORDER = ("decode", "trim", "beats", "snap", "tempo")
GOOD_FILES = ("report.json", "beats.json", "decoded.wav")
# not real audio, the routes only serve the bytes
OLD_WAV = b"RIFF-the-wav-the-old-report-was-made-from"
NEW_WAV = b"RIFF-the-wav-from-the-new-run"
CUT_OFF_WAV = b"RIFF-cut-off"
SET_BPM = {"op": "set_bpm", "segment": 0, "bpm": 90.0}
SILENT = {"stage": "trim", "message": "audio is silent"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # the hand-built jobs carry fixed dates from early 2026, retention would delete them at startup
    return Settings(data_dir=tmp_path / "data", retention_days=0)


@pytest.fixture
def client(settings: Settings):
    # as a context manager so the lifespan (recover / shutdown) actually runs
    with TestClient(create_app(settings)) as c:
        yield c


def make_report(bpm: float = 120.0, edits: list[Edit] | None = None) -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename="song.mp3",
            sha256="0" * 64,
            duration_ms=22000.0,
            sample_rate=44100,
            codec="pcm_f32le",
            decoder_padding_samples=0,
        ),
        trim=Trim(start_ms=2000.0, end_ms=21500.0),
        tempo_map=[TempoSegment(start_ms=2000.0, end_ms=21500.0, bpm=bpm, anchor_ms=2000.0, confidence=1.0, source="auto")],
        edits=edits or [],
    )


def make_beats(tracker: str = "madmom") -> BeatsFile:
    beats = [
        Beat(
            time_ms=2000.0 + 500.0 * i,
            raw_time_ms=2000.0 + 500.0 * i,
            residual_ms=0.0,
            bar=0,
            beat_in_bar=i + 1,
            is_downbeat=i == 0,
        )
        for i in range(4)
    ]
    return BeatsFile(sha256="0" * 64, tracker=tracker, octave="kept", beats=beats)  # type: ignore[arg-type]


def write_job(
    settings: Settings,
    status: str,
    stage: str,
    error: dict | None = None,
    *,
    report: TimingReport | None = None,
    with_report: bool = True,
) -> str:
    # by hand on purpose, so these don't depend on the storage code that reads them back
    job_id = uuid.uuid4().hex
    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True)
    job = {"job_id": job_id, "filename": "song.mp3", "sha256": "0" * 64, "size_bytes": 1, "created_at": CREATED_AT}
    state = {"status": status, "stage": stage, "error": error, "updated_at": CREATED_AT}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    (job_dir / "original.wav").write_bytes(b"the upload")
    if with_report:
        (job_dir / "report.json").write_text((report or make_report()).model_dump_json(), encoding="utf-8")
        (job_dir / "beats.json").write_text(make_beats().model_dump_json(), encoding="utf-8")
        (job_dir / "decoded.wav").write_bytes(OLD_WAV)
    return job_id


def good_files(job_dir: Path) -> dict[str, bytes]:
    return {name: (job_dir / name).read_bytes() for name in GOOD_FILES}


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job still not finished after {POLL_TIMEOUT_S:.0f}s: {body}"
        time.sleep(0.02)


def reanalyze(client: TestClient, job_id: str) -> dict:
    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 202, resp.text
    return wait_for_job(client, job_id)


def enter_through(on_stage: Callable[[str], None], stage: str) -> None:
    for entered in STAGE_ORDER[: STAGE_ORDER.index(stage) + 1]:
        on_stage(entered)


def fake_analysis(monkeypatch: pytest.MonkeyPatch, behave: Callable[[Path, Callable[[str], None]], object]) -> list[SimpleNamespace]:
    # what run_analysis was called with, one entry per run. entries is what was in the work folder at the start
    calls: list[SimpleNamespace] = []

    def run(original_path, work_dir, filename, sha256, on_stage=None, config=None, previous=None, keep_edits=True):
        calls.append(SimpleNamespace(work_dir=work_dir, previous=previous, keep_edits=keep_edits, entries=names(work_dir)))
        return behave(work_dir, on_stage)

    monkeypatch.setattr("backend.api.jobs.run_analysis", run)
    return calls


def fails_at(stage: str, message: str = "boom") -> Callable[[Path, Callable[[str], None]], object]:
    def behave(work_dir: Path, on_stage: Callable[[str], None]) -> object:
        on_stage("decode")
        # decoding got partway before anything went wrong
        (work_dir / "decoded.wav").write_bytes(CUT_OFF_WAV)
        enter_through(on_stage, stage)
        raise StageError(stage, message)  # type: ignore[arg-type]

    return behave


def succeeds(work_dir: Path, on_stage: Callable[[str], None]) -> object:
    on_stage("decode")
    (work_dir / "decoded.wav").write_bytes(NEW_WAV)
    enter_through(on_stage, "tempo")
    return SimpleNamespace(report=make_report(bpm=100.0), beats=make_beats("librosa"))


# --- a failed re-analysis ---


@pytest.mark.parametrize(
    ("behave", "stage", "message"),
    [
        (fails_at("decode", "ffmpeg not found on PATH"), "decode", "ffmpeg not found on PATH"),
        (fails_at("beats", "found 2 beats between the trim points, need at least 4"), "beats", "found 2 beats between the trim points, need at least 4"),
    ],
    ids=["stage error", "later stage error"],
)
def test_failed_reanalysis_leaves_the_last_good_files_as_they_were(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch, behave, stage: str, message: str
) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    before = good_files(job_dir)
    listed = names(job_dir)
    calls = fake_analysis(monkeypatch, behave)

    body = reanalyze(client, job_id)

    assert body["status"] == "failed"
    assert body["error"] == {"stage": stage, "message": message}
    # it worked in the staging folder, so the cut-off wav never got near the real one
    assert [c.work_dir for c in calls] == [job_dir / RERUN]
    assert good_files(job_dir) == before
    assert not (job_dir / RERUN).exists()
    # nothing new left behind either
    assert names(job_dir) == listed


def test_crash_outside_the_pipeline_also_keeps_the_last_good_files(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    before = good_files(job_dir)

    def crash(work_dir: Path, on_stage: Callable[[str], None]) -> object:
        enter_through(on_stage, "trim")
        (work_dir / "decoded.wav").write_bytes(CUT_OFF_WAV)
        raise ValueError("boom")

    fake_analysis(monkeypatch, crash)

    body = reanalyze(client, job_id)

    assert (body["status"], body["error"]) == ("failed", {"stage": "trim", "message": "boom"})
    assert good_files(job_dir) == before
    assert not (job_dir / RERUN).exists()


def test_job_says_the_last_good_report_is_available(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    fake_analysis(monkeypatch, fails_at("snap", "no onsets"))

    reanalyze(client, job_id)

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "failed",
        "stage": "failed",
        "error": {"stage": "snap", "message": "no onsets"},
        "report_available": True,
    }
    # worked out when it's read, a stored copy would be stale after the next re-analysis
    stored = json.loads((settings.jobs_dir / job_id / "status.json").read_text(encoding="utf-8"))
    assert "report_available" not in stored


def test_last_good_report_beats_and_audio_are_served(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    fake_analysis(monkeypatch, fails_at("beats"))
    reanalyze(client, job_id)

    report = client.get(f"/api/jobs/{job_id}/report")
    assert report.status_code == 200, report.text
    assert TimingReport.model_validate(report.json()) == make_report()

    beats = client.get(f"/api/jobs/{job_id}/beats")
    assert beats.status_code == 200, beats.text
    assert BeatsFile.model_validate(beats.json()) == make_beats()

    audio = client.get(f"/api/jobs/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content == OLD_WAV == (job_dir / "decoded.wav").read_bytes()


def test_edit_on_the_last_good_report_is_appended_and_carried_into_the_next_run(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = Edit(field="tempo_map/0/bpm", old=110.0, new=120.0, timestamp=datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))
    job_id = write_job(settings, "done", "done", report=make_report(edits=[earlier]))
    job_dir = settings.jobs_dir / job_id
    fake_analysis(monkeypatch, fails_at("tempo"))
    reanalyze(client, job_id)

    resp = client.patch(f"/api/jobs/{job_id}/report", json=SET_BPM)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tempo_map"][0]["bpm"] == 90.0
    assert body["tempo_map"][0]["source"] == "manual"
    # the earlier entry first and untouched, then one for the edit, the segment's since it flipped to manual
    assert body["edits"][0] == json.loads(earlier.model_dump_json())
    assert len(body["edits"]) == 2
    edit = body["edits"][1]
    assert edit["field"] == "tempo_map/0"
    assert edit["old"] == {"bpm": 120.0, "confidence": 1.0, "source": "auto"}
    assert edit["new"] == {"bpm": 90.0, "confidence": None, "source": "manual"}
    assert client.get(f"/api/jobs/{job_id}/report").json() == body
    assert TimingReport.model_validate_json((job_dir / "report.json").read_text(encoding="utf-8")) == TimingReport.model_validate(body)
    # still a failed job, the edit doesn't change that
    assert client.get(f"/api/jobs/{job_id}").json()["report_available"] is True

    calls = fake_analysis(monkeypatch, succeeds)
    assert reanalyze(client, job_id)["status"] == "done"
    assert calls[0].previous == TimingReport.model_validate(body)


# --- a first analysis that failed ---


def test_failed_first_analysis_is_still_409_and_has_no_report(
    client: TestClient, settings: Settings
) -> None:
    job_id = write_job(settings, "failed", "failed", SILENT, with_report=False)
    # a decode that got through before the failure, the wav alone doesn't make it a report
    (settings.jobs_dir / job_id / "decoded.wav").write_bytes(CUT_OFF_WAV)

    job = client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200, job.text
    assert job.json() == {"status": "failed", "stage": "failed", "error": SILENT, "report_available": False}

    for resp in (
        client.get(f"/api/jobs/{job_id}/report"),
        client.get(f"/api/jobs/{job_id}/beats"),
        client.get(f"/api/jobs/{job_id}/audio"),
        client.patch(f"/api/jobs/{job_id}/report", json=SET_BPM),
    ):
        assert resp.status_code == 409
        assert resp.json() == {"detail": "job failed at trim: audio is silent"}


@pytest.mark.parametrize(
    ("behave", "final"),
    [
        (fails_at("trim", "audio is silent"), {"status": "failed", "stage": "failed", "error": SILENT, "report_available": False}),
        (succeeds, {"status": "done", "stage": "done", "error": None, "report_available": False}),
    ],
    ids=["fails", "works"],
)
def test_first_analysis_runs_in_the_job_folder(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch, behave, final: dict
) -> None:
    # a failed job with no report, run again from the original
    job_id = write_job(settings, "failed", "failed", SILENT, with_report=False)
    job_dir = settings.jobs_dir / job_id
    calls = fake_analysis(monkeypatch, behave)

    body = reanalyze(client, job_id)

    # nothing to protect yet, so no staging folder
    assert [c.work_dir for c in calls] == [job_dir]
    assert body == final
    assert not (job_dir / RERUN).exists()


# --- while a run is going ---


def test_report_and_patch_are_409_while_a_reanalysis_runs(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    before = good_files(job_dir)
    reached = threading.Event()
    release = threading.Event()

    def hold(work_dir: Path, on_stage: Callable[[str], None]) -> object:
        enter_through(on_stage, "beats")
        reached.set()
        release.wait(POLL_TIMEOUT_S)
        raise StageError("beats", "stopped by the test")

    fake_analysis(monkeypatch, hold)
    try:
        assert client.post(f"/api/jobs/{job_id}/reanalyze").status_code == 202
        assert reached.wait(POLL_TIMEOUT_S)

        job = client.get(f"/api/jobs/{job_id}").json()
        assert (job["status"], job["stage"], job["report_available"]) == ("running", "beats", False)
        assert (job_dir / RERUN).is_dir()

        report = client.get(f"/api/jobs/{job_id}/report")
        assert report.status_code == 409
        assert report.json() == {"detail": "report not ready, job is at beats"}
        assert client.get(f"/api/jobs/{job_id}/beats").status_code == 409
        assert client.get(f"/api/jobs/{job_id}/audio").status_code == 409
        assert client.patch(f"/api/jobs/{job_id}/report", json=SET_BPM).status_code == 409
        assert good_files(job_dir) == before
    finally:
        release.set()

    assert wait_for_job(client, job_id)["status"] == "failed"
    assert good_files(job_dir) == before
    assert not (job_dir / RERUN).exists()


def test_queued_reanalysis_is_409_too(client: TestClient, settings: Settings) -> None:
    job_id = write_job(settings, "queued", "queued")

    assert client.get(f"/api/jobs/{job_id}/report").status_code == 409
    assert client.patch(f"/api/jobs/{job_id}/report", json=SET_BPM).status_code == 409
    assert client.get(f"/api/jobs/{job_id}").json()["report_available"] is False


# --- a re-analysis that works ---


def test_successful_reanalysis_replaces_the_wav_with_the_staged_one(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    calls = fake_analysis(monkeypatch, succeeds)

    body = reanalyze(client, job_id)

    assert body == {"status": "done", "stage": "done", "error": None, "report_available": False}
    assert [c.work_dir for c in calls] == [job_dir / RERUN]
    # the old report is what carries over
    assert calls[0].previous == make_report()
    assert (job_dir / "decoded.wav").read_bytes() == NEW_WAV
    assert client.get(f"/api/jobs/{job_id}/audio").content == NEW_WAV
    assert TimingReport.model_validate(client.get(f"/api/jobs/{job_id}/report").json()) == make_report(bpm=100.0)
    assert BeatsFile.model_validate(client.get(f"/api/jobs/{job_id}/beats").json()) == make_beats("librosa")
    assert not (job_dir / RERUN).exists()
    assert names(job_dir) == sorted(["job.json", "status.json", "original.wav", *GOOD_FILES])


def test_reanalysis_after_a_failed_one_works(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    fake_analysis(monkeypatch, fails_at("decode", "ffmpeg not found on PATH"))
    assert reanalyze(client, job_id)["report_available"] is True

    fake_analysis(monkeypatch, succeeds)
    body = reanalyze(client, job_id)

    assert body == {"status": "done", "stage": "done", "error": None, "report_available": False}
    assert (settings.jobs_dir / job_id / "decoded.wav").read_bytes() == NEW_WAV


def test_leftover_staging_folder_is_emptied_before_a_run(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = write_job(settings, "done", "done")
    leftover = settings.jobs_dir / job_id / RERUN
    leftover.mkdir()
    (leftover / "decoded.wav").write_bytes(b"from a run that never finished")
    calls = fake_analysis(monkeypatch, succeeds)

    assert reanalyze(client, job_id)["status"] == "done"

    assert calls[0].entries == []
    assert (settings.jobs_dir / job_id / "decoded.wav").read_bytes() == NEW_WAV
    assert not leftover.exists()


# --- restart ---


@pytest.mark.parametrize(
    ("status", "stage", "requeued", "failed"),
    [("running", "beats", False, 1), ("queued", "queued", True, 0), ("done", "done", False, 0), ("failed", "failed", False, 0)],
)
def test_recover_removes_a_leftover_staging_folder(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, status: str, stage: str, requeued: bool, failed: int
) -> None:
    job_id = write_job(settings, status, stage, SILENT if status == "failed" else None)
    job_dir = settings.jobs_dir / job_id
    (job_dir / RERUN).mkdir()
    (job_dir / RERUN / "decoded.wav").write_bytes(CUT_OFF_WAV)
    before = good_files(job_dir)
    # a queued job is only handed to the runner here, a real run would make the staging folder again
    submitted: list[str] = []
    monkeypatch.setattr(JobRunner, "submit", lambda self, queued_id, **_: submitted.append(queued_id))
    expected = [job_id] if requeued else []

    store = JobStore(settings.jobs_dir)
    runner = JobRunner(store, settings)
    try:
        assert runner.recover() == (expected, failed)
    finally:
        runner.shutdown()

    assert submitted == expected
    assert not (job_dir / RERUN).exists()
    assert good_files(job_dir) == before
    status_now = store.read_status(job_id)
    assert status_now is not None
    # only a running job is failed, a queued one stays queued on disk until the runner takes it
    assert status_now.status == ("failed" if status == "running" else status)


def test_restart_during_a_reanalysis_still_serves_the_last_good_report(settings: Settings) -> None:
    job_id = write_job(settings, "running", "snap")
    job_dir = settings.jobs_dir / job_id
    (job_dir / RERUN).mkdir()
    (job_dir / RERUN / "decoded.wav").write_bytes(CUT_OFF_WAV)
    before = good_files(job_dir)

    with TestClient(create_app(settings)) as client:
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "failed"
        assert job["error"] == {"stage": "snap", "message": "server restarted before the job finished"}
        assert job["report_available"] is True
        assert client.get(f"/api/jobs/{job_id}/report").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/audio").content == OLD_WAV

    assert not (job_dir / RERUN).exists()
    assert good_files(job_dir) == before
