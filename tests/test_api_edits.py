"""Tests for the offset edit, beats and audio routes, done jobs are built by hand so only one test needs ffmpeg."""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.settings import Settings
from backend.schema.models import AudioSource, Beat, BeatsFile, TempoSegment, TimingReport, Trim
from tests.synth import ClickTrackSpec, cached_click_wav

POLL_TIMEOUT_S = 60.0
DURATION_MS = 22000.0
FIRST_BEAT_MS = 2000.0
JSON_HEADERS = {"content-type": "application/json"}


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


def wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while True:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("done", "failed"):
            return body
        assert time.monotonic() < deadline, f"job still not finished after {POLL_TIMEOUT_S:.0f}s: {body}"
        time.sleep(0.05)


def write_job_dir(settings: Settings, status: str, stage: str, error: dict | None = None) -> str:
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
    state = {"status": status, "stage": stage, "error": error, "updated_at": "2026-01-01T00:00:00.000+00:00"}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    return job_id


def make_report(beat_offset_ms: float | None = FIRST_BEAT_MS) -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename="song.mp3",
            sha256="0" * 64,
            duration_ms=DURATION_MS,
            sample_rate=44100,
            codec="pcm_f32le",
            decoder_padding_samples=0,
        ),
        trim=Trim(start_ms=2000.0, end_ms=21500.0),
        beat_offset_ms=beat_offset_ms,
        tempo_map=[TempoSegment(start_ms=2000.0, bpm=120.0, confidence=1.0, source="auto")],
    )


def make_beats() -> BeatsFile:
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
    return BeatsFile(sha256="0" * 64, tracker="madmom", beats=beats)


def add_files(
    settings: Settings,
    job_id: str,
    report: TimingReport | None = None,
    *,
    beats: bool = True,
    audio: bool = True,
) -> Path:
    job_dir = settings.jobs_dir / job_id
    report = make_report() if report is None else report
    (job_dir / "report.json").write_text(report.model_dump_json(), encoding="utf-8")
    if beats:
        (job_dir / "beats.json").write_text(make_beats().model_dump_json(), encoding="utf-8")
    if audio:
        t = np.arange(int(0.2 * 44100)) / 44100
        tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sf.write(job_dir / "decoded.wav", tone, 44100, subtype="FLOAT")
    return job_dir


def write_done_job(settings: Settings, report: TimingReport | None = None, **kwargs) -> str:
    job_id = write_job_dir(settings, "done", "done")
    add_files(settings, job_id, report, **kwargs)
    return job_id


def patch_offset(client: TestClient, job_id: str, value):
    return client.patch(f"/api/jobs/{job_id}/report", json={"beat_offset_ms": value})


def stored_report(settings: Settings, job_id: str) -> TimingReport:
    text = (settings.jobs_dir / job_id / "report.json").read_text(encoding="utf-8")
    return TimingReport.model_validate_json(text)


def snapshot(root: Path) -> dict[str, bytes | None]:
    # folders count too, so a stray temp file or a new job dir shows up
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in sorted(root.rglob("*"))}


def test_patch_sets_offset_and_appends_one_edit(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    before = datetime.now(timezone.utc)
    resp = patch_offset(client, job_id, 2100.5)
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["beat_offset_ms"] == 2100.5
    assert len(body["edits"]) == 1
    edit = body["edits"][0]
    assert set(edit) == {"field", "old", "new", "timestamp"}
    assert edit["field"] == "beat_offset_ms"
    assert edit["old"] == 2000.0
    assert edit["new"] == 2100.5
    stamp = datetime.fromisoformat(edit["timestamp"])
    assert stamp.utcoffset() is not None
    assert before <= stamp <= after

    # only the offset and the edit log move
    expected = make_report().model_copy(update={"beat_offset_ms": 2100.5})
    assert TimingReport.model_validate(body).model_copy(update={"edits": []}) == expected
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)
    assert client.get(f"/api/jobs/{job_id}/report").json() == body


def test_first_offset_has_a_null_old(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report(beat_offset_ms=None))

    resp = patch_offset(client, job_id, 1500.0)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["beat_offset_ms"] == 1500.0
    assert [(e["old"], e["new"]) for e in body["edits"]] == [(None, 1500.0)]


def test_offset_is_rounded_to_three_decimals(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    # what a few 1 ms float steps leave in the last digits
    resp = patch_offset(client, job_id, 138.50600000000003)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["beat_offset_ms"] == 138.506
    assert body["edits"][0]["new"] == 138.506
    assert stored_report(settings, job_id).beat_offset_ms == 138.506


@pytest.mark.parametrize("value", [2000.0, 2000.0004], ids=["same value", "rounds to the same value"])
def test_current_offset_is_not_a_change(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)

    resp = patch_offset(client, job_id, value)
    assert resp.status_code == 200, resp.text
    assert TimingReport.model_validate(resp.json()) == make_report()
    assert resp.json()["edits"] == []
    assert stored_report(settings, job_id) == make_report()


def test_resending_an_edited_offset_adds_nothing(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    first = patch_offset(client, job_id, 2250.0)
    again = patch_offset(client, job_id, 2250.0)
    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    assert len(stored_report(settings, job_id).edits) == 1


def test_edits_are_append_only(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    previous: list[dict] = []
    values = [2100.0, 2250.5, 1900.25]
    for i, value in enumerate(values):
        resp = patch_offset(client, job_id, value)
        assert resp.status_code == 200, resp.text
        edits = resp.json()["edits"]
        assert len(edits) == i + 1
        # earlier entries come back byte for byte, timestamps included
        assert edits[:i] == previous
        previous = edits

    assert [e["new"] for e in previous] == values
    assert [e["old"] for e in previous] == [2000.0, *values[:-1]]
    assert all(e["field"] == "beat_offset_ms" for e in previous)

    report = stored_report(settings, job_id)
    assert report.beat_offset_ms == values[-1]
    assert [e.model_dump(mode="json") for e in report.edits] == previous
    assert client.get(f"/api/jobs/{job_id}/report").json() == resp.json()


@pytest.mark.parametrize("value", [0.0, DURATION_MS])
def test_offset_at_the_edges_of_the_range_is_allowed(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)

    resp = patch_offset(client, job_id, value)
    assert resp.status_code == 200, resp.text
    assert resp.json()["beat_offset_ms"] == value


@pytest.mark.parametrize("value", [-0.001, DURATION_MS + 0.001, -5000.0, 1e9])
def test_offset_outside_the_audio_is_422(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    resp = patch_offset(client, job_id, value)
    assert resp.status_code == 422
    assert "beat_offset_ms" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"beat_offset_ms": 2100.0, "tempo": 120},
        {"offset_ms": 2100.0},
        {"beat_offset_ms": "abc"},
        # lax float parsing would take a string that looks like a number
        {"beat_offset_ms": "2100"},
    ],
    ids=["missing key", "extra key", "typo'd key", "string", "numeric string"],
)
def test_bad_patch_body_is_422(client: TestClient, settings: Settings, body: dict) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    resp = client.patch(f"/api/jobs/{job_id}/report", json=body)
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_422(settings: Settings, literal: str) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    # a real client only sees the response, so the test client shouldn't re-raise a server error
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        # raw body, the json encoder refuses to write these
        resp = client.patch(
            f"/api/jobs/{job_id}/report",
            content=f'{{"beat_offset_ms": {literal}}}'.encode(),
            headers=JSON_HEADERS,
        )
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("job_id", [uuid.uuid4().hex, "not-a-job"])
def test_unknown_job_is_404_on_the_edit_routes(client: TestClient, settings: Settings, job_id: str) -> None:
    # a real job sits next to it, so a stray write into the wrong folder would show
    write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    assert patch_offset(client, job_id, 2100.0).status_code == 404
    for suffix in ("beats", "audio"):
        resp = client.get(f"/api/jobs/{job_id}/{suffix}")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "job not found"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    ("status", "stage", "error"),
    [
        ("queued", "queued", None),
        ("running", "tempo", None),
        ("failed", "failed", {"stage": "trim", "message": "audio is silent"}),
    ],
)
def test_patch_on_an_unfinished_job_is_409_and_writes_nothing(
    client: TestClient, settings: Settings, status: str, stage: str, error: dict | None
) -> None:
    # written after startup, so recover() has already run and leaves them alone
    job_id = write_job_dir(settings, status, stage, error)
    # files are there on purpose, it's the status that has to stop the edit
    add_files(settings, job_id)
    before = snapshot(settings.jobs_dir)

    resp = patch_offset(client, job_id, 2100.0)
    assert resp.status_code == 409
    if error:
        assert resp.json()["detail"] == "job failed at trim: audio is silent"
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("route", ["beats", "audio"])
@pytest.mark.parametrize(
    ("status", "stage", "error"),
    [
        ("queued", "queued", None),
        ("running", "snap", None),
        ("failed", "failed", {"stage": "decode", "message": "boom"}),
    ],
)
def test_beats_and_audio_are_409_until_the_job_is_done(
    client: TestClient, settings: Settings, route: str, status: str, stage: str, error: dict | None
) -> None:
    job_id = write_job_dir(settings, status, stage, error)
    add_files(settings, job_id)

    resp = client.get(f"/api/jobs/{job_id}/{route}")
    assert resp.status_code == 409
    if error:
        assert resp.json()["detail"] == "job failed at decode: boom"


def test_concurrent_patches_lose_no_edit(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    # none of them equals the starting 2000.0, so every request is a real change
    values = [2001.0 + i for i in range(20)]

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(lambda v: patch_offset(client, job_id, v), values))
    assert [r.status_code for r in responses] == [200] * 20

    report = stored_report(settings, job_id)
    assert len(report.edits) == 20
    assert sorted(e.new for e in report.edits) == values
    # a read-modify-write that lost an update would break the chain here
    assert report.edits[0].old == 2000.0
    for earlier, later in zip(report.edits, report.edits[1:]):
        assert later.old == earlier.new
    assert report.beat_offset_ms == report.edits[-1].new
    assert client.get(f"/api/jobs/{job_id}/report").json() == report.model_dump(mode="json")


def test_schema_1_0_report_is_409_for_get_and_patch(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    old = make_report().model_dump(mode="json")
    old["schema_version"] = "1.0"
    del old["source"]["codec"]
    del old["source"]["decoder_padding_samples"]
    (settings.jobs_dir / job_id / "report.json").write_text(json.dumps(old), encoding="utf-8")
    before = snapshot(settings.jobs_dir)

    for resp in (client.get(f"/api/jobs/{job_id}/report"), patch_offset(client, job_id, 2100.0)):
        assert resp.status_code == 409
        assert "upload the file again" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


def test_beats_returns_the_beats_file(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    resp = client.get(f"/api/jobs/{job_id}/beats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tracker"] == "madmom"
    assert len(body["beats"]) == 4
    assert BeatsFile.model_validate(body) == make_beats()
    assert body == json.loads((settings.jobs_dir / job_id / "beats.json").read_text(encoding="utf-8"))


def test_done_job_without_a_beats_file_is_409(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, beats=False)

    resp = client.get(f"/api/jobs/{job_id}/beats")
    assert resp.status_code == 409
    assert "upload the file again" in resp.json()["detail"]


def test_audio_is_the_decoded_wav(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    resp = client.get(f"/api/jobs/{job_id}/audio")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content == (settings.jobs_dir / job_id / "decoded.wav").read_bytes()


def test_audio_range_request_is_206(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    data = (settings.jobs_dir / job_id / "decoded.wav").read_bytes()

    resp = client.get(f"/api/jobs/{job_id}/audio", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206, resp.text
    assert len(resp.content) == 100
    assert resp.content == data[:100]
    assert resp.headers["content-range"] == f"bytes 0-99/{len(data)}"


def test_done_job_without_decoded_wav_is_404(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, audio=False)

    resp = client.get(f"/api/jobs/{job_id}/audio")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "decoded audio is missing"}


@pytest.mark.ffmpeg
def test_edit_beats_and_audio_after_a_real_analysis(client: TestClient, settings: Settings) -> None:
    path, _ = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0, accent_downbeats=True))

    resp = upload(client, "click 120.wav", path.read_bytes())
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "done"

    analysed = client.get(f"/api/jobs/{job_id}/report").json()["beat_offset_ms"]
    assert analysed is not None

    resp = patch_offset(client, job_id, analysed + 1.0)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["edits"]) == 1
    assert body["edits"][0]["old"] == analysed
    assert body["edits"][0]["new"] == round(analysed + 1.0, 3)
    assert body["beat_offset_ms"] == round(analysed + 1.0, 3)
    assert client.get(f"/api/jobs/{job_id}/report").json() == body

    audio = client.get(f"/api/jobs/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.content == (settings.jobs_dir / job_id / "decoded.wav").read_bytes()

    beats = client.get(f"/api/jobs/{job_id}/beats")
    assert beats.status_code == 200
    assert len(beats.json()["beats"]) == 40
    assert beats.json()["tracker"] in ("madmom", "librosa")
