"""Re-analysis: it runs every stage again, replaces the auto results, and moves the job up the recent list."""

from __future__ import annotations

import json
import threading
import time
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
    # 3/2, x2 would be a notation choice and leave it auto
    resp = client.patch(f"/api/jobs/{job_id}/report", json={"op": "set_bpm", "segment": 1, "bpm": 225.0})
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


# --- reset to auto (milestone 7b) ---


def _click_job(client: TestClient) -> tuple[str, dict]:
    spec = ClickTrackSpec(bpm=120, beats=64, lead_silence_s=1.0, accent_downbeats=True)
    path, _ = cached_click_wav(spec)
    job_id = client.post("/api/jobs", files={"file": ("steady.wav", path.read_bytes(), "application/octet-stream")}).json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "done"
    return job_id, client.get(f"/api/jobs/{job_id}/report").json()


def _patch(client: TestClient, job_id: str, body: dict) -> dict:
    resp = client.patch(f"/api/jobs/{job_id}/report", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.ffmpeg
def test_a_manual_segment_one_beat_off_resets_to_the_analysis(client: TestClient) -> None:
    job_id, first = _click_job(client)
    (auto,) = first["tempo_map"]
    _patch(client, job_id, {"op": "set_bpm", "segment": 0, "bpm": auto["bpm"] / 2})
    # one beat at the halved bpm late, the way a stale hand-halved segment kept its old anchor
    late = auto["anchor_ms"] + 2 * 60000.0 / auto["bpm"]
    nudged = _patch(client, job_id, {"op": "set_anchor", "segment": 0, "anchor_ms": late})
    assert nudged["tempo_map"][0]["source"] == "manual"

    assert reanalyze(client, job_id)["status"] == "done"
    kept = client.get(f"/api/jobs/{job_id}/report").json()
    # the manual segment stays as it was, the analysis under it is in auto_result
    assert kept["tempo_map"] == nudged["tempo_map"]
    assert kept["auto_result"]["tempo_map"][0]["anchor_ms"] == auto["anchor_ms"]

    reset = _patch(client, job_id, {"op": "reset_segment", "segment": 0})
    (seg,) = reset["tempo_map"]
    assert (seg["source"], seg["notation_scale"], seg["anchor_ms"]) == ("auto", 0.5, auto["anchor_ms"])
    assert seg["bpm"] == auto["bpm"] / 2
    assert len(reset["edits"]) == len(kept["edits"]) + 1
    assert reset["edits"][-1]["field"] == "tempo_map"
    assert reset["edits"][-1]["new"] == reset["tempo_map"]
    # nothing left to reset
    assert client.patch(f"/api/jobs/{job_id}/report", json={"op": "reset_segment", "segment": 0}).status_code == 422


def test_reset_on_a_report_without_an_analysis_result_says_why(client: TestClient, settings: Settings) -> None:
    job_id = write_job(settings, "done", "done")
    _patch(client, job_id, {"op": "set_bpm", "segment": 0, "bpm": 91.0})
    resp = client.patch(f"/api/jobs/{job_id}/report", json={"op": "reset_segment", "segment": 0})
    assert resp.status_code == 422
    assert "analyze it again" in resp.json()["detail"]


# --- keep my edits or start fresh ---


def test_the_reanalyze_mode_reaches_the_pipeline(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = write_job(settings, "done", "done")
    calls = fake_analysis(monkeypatch, succeeds)

    assert reanalyze(client, job_id)["status"] == "done"
    resp = client.post(f"/api/jobs/{job_id}/reanalyze?mode=fresh")
    assert resp.status_code == 202, resp.text
    assert wait_for_job(client, job_id)["status"] == "done"
    assert [c.keep_edits for c in calls] == [True, False]
    assert client.post(f"/api/jobs/{job_id}/reanalyze?mode=everything").status_code == 422


@pytest.mark.ffmpeg
def test_halving_stays_a_notation_choice_through_reanalysis_and_start_fresh_drops_it(client: TestClient) -> None:
    job_id, first = _click_job(client)
    (auto,) = first["tempo_map"]
    halved = _patch(client, job_id, {"op": "set_bpm", "segment": 0, "bpm": auto["bpm"] / 2})
    (seg,) = halved["tempo_map"]
    assert (seg["source"], seg["notation_scale"], seg["confidence"]) == ("auto", 0.5, auto["confidence"])
    (edit,) = halved["edits"]
    assert edit["field"] == "tempo_map/0"
    assert edit["new"] == {"bpm": auto["bpm"] / 2, "notation_scale": 0.5}

    # keep my edits: the new auto segment, with the /2 on top
    assert reanalyze(client, job_id)["status"] == "done"
    kept = client.get(f"/api/jobs/{job_id}/report").json()
    (seg,) = kept["tempo_map"]
    assert (seg["source"], seg["notation_scale"], seg["bpm"]) == ("auto", 0.5, auto["bpm"] / 2)
    assert kept["auto_result"]["tempo_map"] == first["tempo_map"]
    assert kept["edits"] == halved["edits"]

    # start fresh: the analysis as it comes, and one entry that says what went
    resp = client.post(f"/api/jobs/{job_id}/reanalyze?mode=fresh")
    assert resp.status_code == 202, resp.text
    assert wait_for_job(client, job_id)["status"] == "done"
    fresh = client.get(f"/api/jobs/{job_id}/report").json()
    assert fresh["tempo_map"] == first["tempo_map"]
    assert fresh["edits"][:-1] == halved["edits"]
    dropped = fresh["edits"][-1]
    assert dropped["field"] == ""
    assert dropped["old"]["tempo_map"] == kept["tempo_map"]
    assert dropped["new"]["tempo_map"] == first["tempo_map"]

    # nothing manual left, so starting fresh again logs nothing
    client.post(f"/api/jobs/{job_id}/reanalyze?mode=fresh")
    assert wait_for_job(client, job_id)["status"] == "done"
    assert client.get(f"/api/jobs/{job_id}/report").json()["edits"] == fresh["edits"]


# --- cancel ---


def _held_at_trim(gate: threading.Event, started: threading.Event):
    def behave(work_dir: Path, on_stage):
        on_stage("decode")
        started.set()
        gate.wait(10)
        # the runner says stop here
        on_stage("trim")
        return succeeds(work_dir, on_stage)

    return behave


@pytest.mark.ffmpeg
def test_cancelling_a_first_analysis_deletes_the_job(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    gate, started = threading.Event(), threading.Event()
    fake_analysis(monkeypatch, _held_at_trim(gate, started))
    # ingest runs ffprobe on the upload, so it has to be real audio
    path, _ = cached_click_wav(ClickTrackSpec(bpm=120, beats=16, lead_silence_s=0.5))
    job_id = client.post("/api/jobs", files={"file": ("a.wav", path.read_bytes(), "application/octet-stream")}).json()["job_id"]
    assert started.wait(10)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    gate.set()
    deadline = time.monotonic() + 10
    while client.get(f"/api/jobs/{job_id}").status_code != 404:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert not (settings.jobs_dir / job_id).exists()


def test_cancelling_a_reanalysis_goes_back_to_the_report_it_had(client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = write_job(settings, "done", "done")
    job_dir = settings.jobs_dir / job_id
    before = {name: (job_dir / name).read_bytes() for name in ("report.json", "beats.json", "decoded.wav")}
    gate, started = threading.Event(), threading.Event()
    fake_analysis(monkeypatch, _held_at_trim(gate, started))

    assert client.post(f"/api/jobs/{job_id}/reanalyze").status_code == 202
    assert started.wait(10)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 202
    gate.set()
    assert wait_for_job(client, job_id)["status"] == "done"
    assert {name: (job_dir / name).read_bytes() for name in before} == before
    assert not (job_dir / ".rerun").exists()
    # nothing is running any more
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409


def test_cancel_needs_a_job_that_runs(client: TestClient, settings: Settings) -> None:
    assert client.post(f"/api/jobs/{'0' * 32}/cancel").status_code == 404
    job_id = write_job(settings, "done", "done")
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409
