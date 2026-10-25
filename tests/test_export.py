"""The timing export and the Sonolus preset: schema checks, the route, the cli, and one real mp3."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import signal

from backend.analysis import export as export_cli
from backend.analysis.export import ExportError, timing_export
from backend.api.app import create_app
from backend.api.models import JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import (
    AudioSource,
    Beat,
    BeatsFile,
    GridFeature,
    MeterSegment,
    TempoSegment,
    TimingReport,
    Trim,
)
from backend.schema.validate import SchemaMismatch, validate
from tests.synth import ClickTrackSpec, cached_click_wav

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SHA = "cd" * 32
POLL_TIMEOUT_S = 60.0


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


def make_report(filename: str = "song.mp3") -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename=filename,
            sha256=SHA,
            duration_ms=21000.0,
            sample_rate=44100,
            codec="mp3",
            decoder_padding_samples=1105,
        ),
        trim=Trim(start_ms=500.0, end_ms=20500.0),
        tempo_map=[
            TempoSegment(start_ms=500.0, end_ms=10500.0, bpm=120.0, anchor_ms=1000.0, confidence=0.98, source="auto"),
            TempoSegment(start_ms=10500.0, end_ms=20500.0, bpm=150.0, anchor_ms=10500.0, confidence=None, source="manual"),
        ],
        meter_map=[MeterSegment(start_ms=500.0, end_ms=20500.0, numerator=4, denominator=4, confidence=0.9, source="auto")],
    )


def make_beats(sha256: str = SHA) -> BeatsFile:
    beats = [
        Beat(time_ms=1000.0 + 500.0 * i, raw_time_ms=988.2 + 500.0 * i, residual_ms=0.0, bar=i // 4, beat_in_bar=i % 4 + 1, is_downbeat=i % 4 == 0)
        for i in range(19)
    ]
    features = [GridFeature(time_ms=1000.0 + 250.0 * i, low=0.1, mid=1.0, high=0.2) for i in range(38)]
    return BeatsFile(sha256=sha256, tracker="madmom", octave="kept", beats=beats, grid_features=features)


def write_done_job(settings: Settings, report: TimingReport, beats: BeatsFile | None = None) -> str:
    store = JobStore(settings.jobs_dir)
    job_id, job_dir = store.create()
    (job_dir / "original.mp3").write_bytes(b"not audio, nothing here decodes it")
    store.write_job(job_id, report.source.filename, report.source.sha256, 34)
    store.write_report(job_id, report)
    if beats is not None:
        store.write_beats(job_id, beats)
    store.write_status(job_id, JobStatus(status="done", stage="done"))
    return job_id


# --- the export itself ---


def test_timing_export_without_beats_validates_and_leaves_beats_out() -> None:
    report = make_report()

    doc = timing_export(report, None, NOW)

    validate(doc, "timing_export.schema.json")
    assert set(doc) == {"kind", "exported_at", "report"}
    assert doc["kind"] == "timing"
    assert TimingReport.model_validate(doc["report"]) == report


def test_timing_export_with_beats_validates_and_carries_them() -> None:
    report, beats = make_report(), make_beats()

    doc = timing_export(report, beats, NOW)

    validate(doc, "timing_export.schema.json")
    assert set(doc) == {"kind", "exported_at", "report", "beats"}
    assert BeatsFile.model_validate(doc["beats"]) == beats
    # timing numbers only, nothing in there could be audio
    assert set(doc["beats"]) == {"schema_version", "sha256", "tracker", "octave", "beats", "grid_features", "cross_check_beats"}


@pytest.mark.parametrize(
    "spoil",
    [
        lambda d: d.update(beats=None),
        lambda d: d.update(extra=1),
        lambda d: d["report"]["tempo_map"][0].pop("anchor_ms"),
        lambda d: d["report"].update(beat_offset_ms=1000.0),
        lambda d: d.update(kind="sonolus"),
    ],
    ids=["null beats", "unknown key", "segment without an anchor", "beat_offset_ms is gone", "wrong kind"],
)
def test_the_committed_schema_rejects_a_spoiled_export(spoil) -> None:
    doc = timing_export(make_report(), None, NOW)
    spoil(doc)

    with pytest.raises(SchemaMismatch, match="timing_export.schema.json"):
        validate(doc, "timing_export.schema.json")


def test_beats_from_another_file_are_refused() -> None:
    with pytest.raises(ExportError, match="another source file"):
        timing_export(make_report(), make_beats(sha256="ef" * 32), NOW)


# --- GET /api/jobs/{id}/export ---


def test_export_route_returns_the_timing_json_as_a_download(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report(), make_beats())

    resp = client.get(f"/api/jobs/{job_id}/export")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == "attachment; filename=\"song.timing.json\"; filename*=UTF-8''song.timing.json"
    doc = resp.json()
    validate(doc, "timing_export.schema.json")
    assert "beats" not in doc
    assert doc["report"] == client.get(f"/api/jobs/{job_id}/report").json()


@pytest.mark.parametrize("flag", ["true", "1"])
def test_export_route_adds_beats_only_when_asked(client: TestClient, settings: Settings, flag: str) -> None:
    job_id = write_done_job(settings, make_report(), make_beats())

    resp = client.get(f"/api/jobs/{job_id}/export", params={"beats": flag})

    assert resp.status_code == 200, resp.text
    validate(resp.json(), "timing_export.schema.json")
    assert resp.json()["beats"] == client.get(f"/api/jobs/{job_id}/beats").json()


def test_export_carries_the_edits(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report())
    patched = client.patch(f"/api/jobs/{job_id}/report", json={"op": "set_bpm", "segment": 1, "bpm": 300.0})
    assert patched.status_code == 200, patched.text

    doc = client.get(f"/api/jobs/{job_id}/export").json()

    assert doc["report"]["edits"] == patched.json()["edits"]
    assert len(doc["report"]["edits"]) == 1


@pytest.mark.parametrize(("compensation", "offset"), [(None, -1.0), ("25.057", -0.974943)])
def test_export_route_sonolus_preset(client: TestClient, settings: Settings, compensation: str | None, offset: float) -> None:
    job_id = write_done_job(settings, make_report())
    params = {"preset": "sonolus"}
    if compensation is not None:
        params["decoder_compensation_ms"] = compensation

    resp = client.get(f"/api/jobs/{job_id}/export", params=params)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"].startswith('attachment; filename="song.sonolus.json"')
    doc = resp.json()
    validate(doc, "sonolus_export.schema.json")
    assert doc["level_data"]["bgmOffset"] == offset
    assert [(c["beat"], c["bpm"]) for c in doc["bpm_changes"]] == [(0.0, 120.0), (23.0, 150.0)]


def test_a_japanese_title_keeps_its_name_in_the_download(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report("テスト曲 120.wav"))

    resp = client.get(f"/api/jobs/{job_id}/export")

    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert 'filename="____ 120.timing.json"' in disposition
    assert "filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88%E6%9B%B2%20120.timing.json" in disposition


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"preset": "sonolus", "beats": "true"}, "beats only go in the timing export"),
        ({"decoder_compensation_ms": "25"}, "decoder compensation is for the sonolus preset"),
        ({"preset": "sonolus", "decoder_compensation_ms": "5000"}, None),
        ({"preset": "sonolus", "decoder_compensation_ms": "nan"}, None),
        ({"preset": "osu"}, None),
    ],
    ids=["beats with sonolus", "compensation with timing", "compensation too big", "nan", "unknown preset"],
)
def test_bad_export_options_are_422(client: TestClient, settings: Settings, params: dict, detail: str | None) -> None:
    job_id = write_done_job(settings, make_report())

    resp = client.get(f"/api/jobs/{job_id}/export", params=params)

    assert resp.status_code == 422, resp.text
    if detail is not None:
        assert resp.json()["detail"] == detail


def test_export_of_an_unknown_job_is_404(client: TestClient) -> None:
    assert client.get(f"/api/jobs/{'0' * 32}/export").status_code == 404


def test_export_is_409_until_the_job_is_done(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report())
    JobStore(settings.jobs_dir).write_status(job_id, JobStatus(status="running", stage="tempo"))

    resp = client.get(f"/api/jobs/{job_id}/export")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "export not ready, job is at tempo"


def test_beats_asked_for_but_missing_is_409(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings, make_report())

    resp = client.get(f"/api/jobs/{job_id}/export", params={"beats": "true"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == "no beats file for this job, upload the file again"


# --- the cli ---


def test_cli_prints_the_plain_export(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    beats_path = tmp_path / "beats.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")
    beats_path.write_text(make_beats().model_dump_json(), encoding="utf-8")

    assert export_cli.main([str(report_path), "--beats", str(beats_path)]) == 0

    doc = json.loads(capsys.readouterr().out)
    validate(doc, "timing_export.schema.json")
    assert len(doc["beats"]["beats"]) == 19


def test_cli_sonolus_with_the_padding_preset(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")

    assert export_cli.main([str(report_path), "--sonolus", "--decoder-padding"]) == 0

    doc = json.loads(capsys.readouterr().out)
    # 1105 samples at 44.1 kHz
    assert doc["decoder_compensation_ms"] == 25.057
    assert doc["level_data"]["bgmOffset"] == -0.974943


def test_cli_refuses_compensation_on_the_plain_export(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")

    assert export_cli.main([str(report_path), "--decoder-compensation-ms", "25"]) == 1
    assert "only goes with --sonolus" in capsys.readouterr().err


# --- a real mp3 through the app, checked against a decoder that ignores the gapless header ---


def _decode_f32(src: Path, naive: bool) -> np.ndarray:
    flags = ["-flags2", "+skip_manual"] if naive else []
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", *flags, "-i", str(src), "-ac", "1", "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _lag_samples(late: np.ndarray, early: np.ndarray) -> int:
    corr = signal.correlate(late.astype(np.float64), early.astype(np.float64), mode="full", method="fft")
    return int(signal.correlation_lags(len(late), len(early), mode="full")[np.argmax(corr)])


@pytest.mark.ffmpeg
def test_sonolus_offset_lines_up_a_naive_decoder_with_the_grid(client: TestClient, tmp_path: Path) -> None:
    spec = ClickTrackSpec(bpm=120, beats=32, lead_silence_s=0.1375, accent_downbeats=True)
    wav, track = cached_click_wav(spec)
    mp3 = tmp_path / "click.mp3"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)],
        check=True,
    )

    job_id = client.post("/api/jobs", files={"file": ("click.mp3", mp3.read_bytes(), "audio/mpeg")}).json()["job_id"]
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while (status := client.get(f"/api/jobs/{job_id}").json())["status"] not in ("done", "failed"):
        assert time.monotonic() < deadline, status
        time.sleep(0.05)
    assert status["status"] == "done", status
    report = client.get(f"/api/jobs/{job_id}/report").json()
    padding_ms = report["source"]["decoder_padding_samples"] / report["source"]["sample_rate"] * 1000.0
    assert report["source"]["decoder_padding_samples"] == 1105

    # what a player that ignores the lame header hears, the same clicks a little later
    lag_ms = _lag_samples(_decode_f32(mp3, naive=True), _decode_f32(mp3, naive=False)) / spec.sample_rate * 1000.0
    heard_downbeat_s = (track.downbeats_ms[0] + lag_ms) / 1000.0

    def level_error_ms(compensation_ms: float) -> float:
        doc = client.get(
            f"/api/jobs/{job_id}/export", params={"preset": "sonolus", "decoder_compensation_ms": round(compensation_ms, 3)}
        ).json()
        # level time is bgm time minus bgmOffset, and beat b is at b * 0.5 s at 120 bpm
        level_s = heard_downbeat_s - doc["level_data"]["bgmOffset"]
        return (level_s - doc["first_downbeat_beat"] * 0.5) * 1000.0

    # with the padding preset the grid is within the snap's 0.7 ms of the click the player plays
    assert abs(level_error_ms(padding_ms)) <= 1.5
    # without it the notes would be the padding early, 25 ms
    assert level_error_ms(0.0) == pytest.approx(padding_ms, abs=1.5)
