"""Tests for the tempo edit, job list, reanalyze, beats and audio routes, jobs are built by hand so only one test needs ffmpeg."""

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
from backend.api.jobs import JobRunner
from backend.api.settings import Settings
from backend.schema.models import AudioSource, Beat, BeatsFile, Edit, SegmentSource, TempoSegment, TimingReport, Trim
from tests.synth import ClickTrackSpec, cached_click_wav

POLL_TIMEOUT_S = 60.0
DURATION_MS = 22000.0
FIRST_BEAT_MS = 2000.0
TRIM_END_MS = 21500.0
BPM_TOLERANCE = 0.01
ANCHOR_TOLERANCE_MS = 0.01
SHA_A = "a" * 64
SHA_B = "b" * 64
CREATED_AT = "2026-01-01T00:00:00.000+00:00"
JSON_HEADERS = {"content-type": "application/json"}

# one valid body per op, for the three segment report from make_multi_report
EDIT_BODIES = {
    "set_anchor": {"op": "set_anchor", "segment": 1, "anchor_ms": 8100.0},
    "set_bpm": {"op": "set_bpm", "segment": 1, "bpm": 90.0},
    "split": {"op": "split", "at_ms": 5000.0},
    "merge": {"op": "merge", "segment": 0},
    "match": {"op": "match", "segment": 1, "side": "previous"},
}

# the ops that name a segment, to try an index the map doesn't have
SEGMENT_OPS = {
    "set_anchor": lambda i: {"op": "set_anchor", "segment": i, "anchor_ms": 8100.0},
    "set_bpm": lambda i: {"op": "set_bpm", "segment": i, "bpm": 90.0},
    "merge": lambda i: {"op": "merge", "segment": i},
    "match": lambda i: {"op": "match", "segment": i, "side": "previous"},
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # the hand-built jobs carry fixed dates from early 2026, retention would delete them at startup
    return Settings(data_dir=tmp_path / "data", retention_days=0)


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


def write_job_dir(
    settings: Settings,
    status: str,
    stage: str,
    error: dict | None = None,
    *,
    created_at: str = CREATED_AT,
    sha256: str = "0" * 64,
) -> str:
    # by hand on purpose, so these don't depend on the storage code that reads them back
    job_id = uuid.uuid4().hex
    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True)
    job = {
        "job_id": job_id,
        "filename": "song.mp3",
        "sha256": sha256,
        "size_bytes": 1,
        "created_at": created_at,
    }
    state = {"status": status, "stage": stage, "error": error, "updated_at": "2026-01-01T00:00:00.000+00:00"}
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "status.json").write_text(json.dumps(state), encoding="utf-8")
    return job_id


def make_segment(
    start_ms: float,
    end_ms: float,
    bpm: float = 120.0,
    anchor_ms: float | None = None,
    confidence: float | None = 1.0,
    source: SegmentSource = "auto",
) -> TempoSegment:
    return TempoSegment(
        start_ms=start_ms,
        end_ms=end_ms,
        bpm=bpm,
        anchor_ms=start_ms if anchor_ms is None else anchor_ms,
        confidence=confidence,
        source=source,
    )


def make_report(segments: list[TempoSegment] | None = None) -> TimingReport:
    if segments is None:
        segments = [make_segment(FIRST_BEAT_MS, TRIM_END_MS)]
    return TimingReport(
        source=AudioSource(
            filename="song.mp3",
            sha256="0" * 64,
            duration_ms=DURATION_MS,
            sample_rate=44100,
            codec="pcm_f32le",
            decoder_padding_samples=0,
        ),
        trim=Trim(start_ms=segments[0].start_ms, end_ms=segments[-1].end_ms),
        tempo_map=segments,
    )


def make_multi_report() -> TimingReport:
    # three tempos, so a beat of slack or half a beat is a different length in each segment
    return make_report(
        [
            make_segment(2000.0, 8000.0, bpm=120.0, anchor_ms=2010.0),
            make_segment(8000.0, 14000.0, bpm=60.0, anchor_ms=8020.0),
            make_segment(14000.0, TRIM_END_MS, bpm=240.0, anchor_ms=14030.0),
        ]
    )


def make_report_1_1() -> dict:
    # by hand, the way it was stored before 2.0
    return {
        "schema_version": "1.1",
        "source": {
            "filename": "song.mp3",
            "sha256": "0" * 64,
            "duration_ms": DURATION_MS,
            "sample_rate": 44100,
            "codec": "pcm_f32le",
            "decoder_padding_samples": 0,
        },
        "trim": {"start_ms": 2000.0, "end_ms": TRIM_END_MS},
        # not the segment start, so an anchor that came from the start would show
        "beat_offset_ms": 2120.5,
        "tempo_map": [{"start_ms": 2000.0, "bpm": 120.0, "confidence": 1.0, "source": "auto"}],
        "meter_map": [],
        "sections": [],
        "edits": [{"field": "beat_offset_ms", "old": 2000.0, "new": 2120.5, "timestamp": "2026-02-01T10:00:00Z"}],
    }


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
    return BeatsFile(sha256="0" * 64, tracker="madmom", octave="kept", beats=beats)


def grid_beats(count: int, bpm: float = 120.0) -> BeatsFile:
    # a steady grid from the first beat with a downbeat every four, what a refit reads
    period = 60000.0 / bpm
    beats = [
        Beat(
            time_ms=FIRST_BEAT_MS + period * i,
            raw_time_ms=FIRST_BEAT_MS + period * i,
            residual_ms=0.0,
            bar=i // 4,
            beat_in_bar=i % 4 + 1,
            is_downbeat=i % 4 == 0,
        )
        for i in range(count)
    ]
    return BeatsFile(sha256="0" * 64, tracker="madmom", octave="kept", beats=beats)


def add_files(
    settings: Settings,
    job_id: str,
    report: TimingReport | None = None,
    *,
    beats: BeatsFile | bool = True,
    audio: bool = True,
) -> Path:
    job_dir = settings.jobs_dir / job_id
    report = make_report() if report is None else report
    (job_dir / "report.json").write_text(report.model_dump_json(), encoding="utf-8")
    if beats:
        beats_file = make_beats() if beats is True else beats
        (job_dir / "beats.json").write_text(beats_file.model_dump_json(), encoding="utf-8")
    if audio:
        t = np.arange(int(0.2 * 44100)) / 44100
        tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sf.write(job_dir / "decoded.wav", tone, 44100, subtype="FLOAT")
    return job_dir


def write_done_job(settings: Settings, report: TimingReport | None = None, **kwargs) -> str:
    job_id = write_job_dir(settings, "done", "done")
    add_files(settings, job_id, report, **kwargs)
    return job_id


def patch_edit(client: TestClient, job_id: str, body: dict):
    return client.patch(f"/api/jobs/{job_id}/report", json=body)


def patch_anchor(client: TestClient, job_id: str, value, segment: int = 0):
    return patch_edit(client, job_id, {"op": "set_anchor", "segment": segment, "anchor_ms": value})


def patch_bpm(client: TestClient, job_id: str, value, segment: int = 0):
    return patch_edit(client, job_id, {"op": "set_bpm", "segment": segment, "bpm": value})


def patch_split(client: TestClient, job_id: str, at_ms):
    return patch_edit(client, job_id, {"op": "split", "at_ms": at_ms})


def patch_merge(client: TestClient, job_id: str, segment: int):
    return patch_edit(client, job_id, {"op": "merge", "segment": segment})


def stored_report(settings: Settings, job_id: str) -> TimingReport:
    text = (settings.jobs_dir / job_id / "report.json").read_text(encoding="utf-8")
    return TimingReport.model_validate_json(text)


def flat(edit: dict) -> dict[str, tuple]:
    # one entry as path -> (old, new). with several values changed old and new are objects keyed under field
    if not isinstance(edit["old"], dict):
        return {edit["field"]: (edit["old"], edit["new"])}
    assert edit["old"].keys() == edit["new"].keys(), edit
    return {f"{edit['field']}/{key}": (edit["old"][key], edit["new"][key]) for key in edit["old"]}


def changes(edits: list[dict]) -> dict[str, tuple]:
    # one manual change is one entry, however many values it touched
    assert len(edits) == 1, edits
    return flat(edits[0])


def snapshot(root: Path) -> dict[str, bytes | None]:
    # folders count too, so a stray temp file or a new job dir shows up
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None for p in sorted(root.rglob("*"))}


# --- set_anchor ---


def test_set_anchor_on_an_auto_segment_logs_one_entry(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    before = datetime.now(timezone.utc)
    resp = patch_anchor(client, job_id, 2100.5)
    after = datetime.now(timezone.utc)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    segment = body["tempo_map"][0]
    assert (segment["anchor_ms"], segment["source"], segment["confidence"]) == (2100.5, "manual", None)
    # the flip to manual rides along, so the entry is the segment's and holds only what changed
    (edit,) = body["edits"]
    assert set(edit) == {"field", "old", "new", "timestamp"}
    assert edit["field"] == "tempo_map/0"
    assert edit["old"] == {"anchor_ms": 2000.0, "confidence": 1.0, "source": "auto"}
    assert edit["new"] == {"anchor_ms": 2100.5, "confidence": None, "source": "manual"}
    stamp = datetime.fromisoformat(edit["timestamp"])
    assert stamp.utcoffset() is not None
    assert before <= stamp <= after

    # only the segment and the edit log move
    expected = make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, anchor_ms=2100.5, confidence=None, source="manual")])
    assert TimingReport.model_validate(body).model_copy(update={"edits": []}) == expected
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)
    assert client.get(f"/api/jobs/{job_id}/report").json() == body


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"op": "set_anchor", "segment": 0, "anchor_ms": 2100.0}, "anchor_ms"),
        ({"op": "set_bpm", "segment": 0, "bpm": 90.0}, "bpm"),
    ],
    ids=["set_anchor", "set_bpm"],
)
@pytest.mark.parametrize(
    ("segment", "also_logged"),
    [
        (make_segment(FIRST_BEAT_MS, TRIM_END_MS, confidence=None, source="manual"), []),
        (make_segment(FIRST_BEAT_MS, TRIM_END_MS, confidence=0.9, source="manual"), ["confidence"]),
    ],
    ids=["hand-set segment", "refit segment"],
)
def test_edit_on_a_manual_segment_logs_only_what_changed(
    client: TestClient, settings: Settings, body: dict, field: str, segment: TempoSegment, also_logged: list[str]
) -> None:
    job_id = write_done_job(settings, make_report([segment]))

    resp = patch_edit(client, job_id, body)
    assert resp.status_code == 200, resp.text
    # no source in it, it was manual already. one value is logged at its own path, two at the segment's
    (edit,) = resp.json()["edits"]
    assert edit["field"] == ("tempo_map/0" if also_logged else f"tempo_map/0/{field}")
    assert set(flat(edit)) == {f"tempo_map/0/{name}" for name in [field, *also_logged]}


def test_anchor_is_rounded_to_three_decimals(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    # what a few 1 ms float steps leave in the last digits
    resp = patch_anchor(client, job_id, 2138.50600000000003)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tempo_map"][0]["anchor_ms"] == 2138.506
    assert changes(body["edits"])["tempo_map/0/anchor_ms"] == (2000.0, 2138.506)
    assert stored_report(settings, job_id).tempo_map[0].anchor_ms == 2138.506


@pytest.mark.parametrize(
    "body",
    [
        {"op": "set_anchor", "segment": 0, "anchor_ms": 2000.0},
        {"op": "set_anchor", "segment": 0, "anchor_ms": 2000.0004},
        {"op": "set_bpm", "segment": 0, "bpm": 120.0},
        {"op": "set_bpm", "segment": 0, "bpm": 120.0000004},
    ],
    ids=["anchor same value", "anchor rounds to the same value", "bpm same value", "bpm rounds to the same value"],
)
def test_current_value_is_not_a_change(client: TestClient, settings: Settings, body: dict) -> None:
    # already set by hand, an auto segment would be pinned by any edit, see the next test
    report = make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, confidence=None, source="manual")])
    job_id = write_done_job(settings, report)

    resp = patch_edit(client, job_id, body)
    assert resp.status_code == 200, resp.text
    assert TimingReport.model_validate(resp.json()) == report
    assert resp.json()["edits"] == []
    assert stored_report(settings, job_id) == report


@pytest.mark.parametrize(
    "body",
    [
        {"op": "set_anchor", "segment": 0, "anchor_ms": 2000.0},
        {"op": "set_bpm", "segment": 0, "bpm": 120.0},
    ],
    ids=["anchor", "bpm"],
)
def test_current_value_on_an_auto_segment_still_makes_it_manual(client: TestClient, settings: Settings, body: dict) -> None:
    job_id = write_done_job(settings)

    # touching a segment keeps re-analysis off it even when the value stays, so only the flip is logged
    first = patch_edit(client, job_id, body)
    assert first.status_code == 200, first.text
    segment = first.json()["tempo_map"][0]
    assert (segment["anchor_ms"], segment["bpm"], segment["confidence"], segment["source"]) == (2000.0, 120.0, None, "manual")
    assert changes(first.json()["edits"]) == {
        "tempo_map/0/source": ("auto", "manual"),
        "tempo_map/0/confidence": (1.0, None),
    }

    again = patch_edit(client, job_id, body)
    assert again.json() == first.json()


def test_resending_an_edited_anchor_adds_nothing(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    first = patch_anchor(client, job_id, 2250.0)
    again = patch_anchor(client, job_id, 2250.0)
    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    assert len(first.json()["edits"]) == 1
    assert stored_report(settings, job_id).edits == TimingReport.model_validate(first.json()).edits


def test_edits_are_append_only(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    previous: list[dict] = []
    values = [2100.0, 2250.5, 1900.25]
    for i, value in enumerate(values):
        resp = patch_anchor(client, job_id, value)
        assert resp.status_code == 200, resp.text
        edits = resp.json()["edits"]
        assert len(edits) == i + 1
        # earlier entries come back byte for byte, timestamps included
        assert edits[: len(previous)] == previous
        previous = edits

    # the first one also flipped the segment to manual, so it's the segment's entry
    assert [e["field"] for e in previous] == ["tempo_map/0", "tempo_map/0/anchor_ms", "tempo_map/0/anchor_ms"]
    moves = [flat(e)["tempo_map/0/anchor_ms"] for e in previous]
    assert [new for _, new in moves] == values
    assert [old for old, _ in moves] == [2000.0, *values[:-1]]

    report = stored_report(settings, job_id)
    assert report.tempo_map[0].anchor_ms == values[-1]
    assert [e.model_dump(mode="json") for e in report.edits] == previous
    assert client.get(f"/api/jobs/{job_id}/report").json() == resp.json()


# a beat of slack either side of the segment: 500 ms at 120 bpm, 1000 at 60, 250 at 240
@pytest.mark.parametrize("value", [1500.0, TRIM_END_MS + 500.0], ids=["a beat before the start", "a beat after the end"])
def test_anchor_a_beat_outside_the_segment_is_allowed(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)

    resp = patch_anchor(client, job_id, value)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tempo_map"][0]["anchor_ms"] == value


@pytest.mark.parametrize(
    "value",
    [1499.999, TRIM_END_MS + 500.001, -5000.0, 1e9],
    ids=["just before the slack", "just after the slack", "negative", "far past the end"],
)
def test_anchor_further_out_is_422(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    resp = patch_anchor(client, job_id, value)
    assert resp.status_code == 422
    assert "anchor_ms has to be inside segment 0" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    ("segment", "low", "high"),
    [(0, 1500.0, 8500.0), (1, 7000.0, 15000.0), (2, 13750.0, 21750.0)],
    ids=["120 bpm", "60 bpm", "240 bpm"],
)
def test_anchor_slack_is_a_beat_of_the_segments_own_tempo(
    client: TestClient, settings: Settings, segment: int, low: float, high: float
) -> None:
    original = make_multi_report()
    job_id = write_done_job(settings, original)
    before = snapshot(settings.jobs_dir)

    for value in (low - 0.001, high + 0.001):
        assert patch_anchor(client, job_id, value, segment).status_code == 422
    assert snapshot(settings.jobs_dir) == before

    for value in (low, high):
        resp = patch_anchor(client, job_id, value, segment)
        assert resp.status_code == 200, resp.text
        assert resp.json()["tempo_map"][segment]["anchor_ms"] == value
    # the other segments never move
    kept = [s.model_dump(mode="json") for i, s in enumerate(original.tempo_map) if i != segment]
    assert [s for i, s in enumerate(resp.json()["tempo_map"]) if i != segment] == kept


# --- bad bodies, unknown and unfinished jobs ---


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({"segment": 0, "anchor_ms": 2100.0}, id="missing op"),
        pytest.param({"op": "nudge", "segment": 0, "anchor_ms": 2100.0}, id="unknown op"),
        pytest.param({"beat_offset_ms": 2100.0}, id="the old offset body"),
        pytest.param({"op": "set_anchor", "segment": 0, "anchor_ms": 2100.0, "bpm": 120.0}, id="extra key"),
        pytest.param({"op": "set_anchor", "segment": 0, "anchor": 2100.0}, id="typo'd key"),
        pytest.param({"op": "set_anchor", "segment": 0}, id="missing value"),
        pytest.param({"op": "set_anchor", "anchor_ms": 2100.0}, id="missing segment"),
        pytest.param({"op": "set_anchor", "segment": 0, "anchor_ms": "abc"}, id="string"),
        # lax float parsing would take a string that looks like a number
        pytest.param({"op": "set_anchor", "segment": 0, "anchor_ms": "2100"}, id="numeric string"),
        pytest.param({"op": "set_anchor", "segment": 0, "anchor_ms": True}, id="bool anchor"),
        pytest.param({"op": "set_anchor", "segment": 0, "anchor_ms": None}, id="null anchor"),
        pytest.param({"op": "set_anchor", "segment": "0", "anchor_ms": 2100.0}, id="numeric string segment"),
        pytest.param({"op": "set_anchor", "segment": True, "anchor_ms": 2100.0}, id="bool segment"),
        # a negative index must not wrap around to the last segment
        pytest.param({"op": "set_anchor", "segment": -1, "anchor_ms": 2100.0}, id="negative segment"),
        pytest.param({"op": "set_bpm", "segment": 0, "bpm": "90"}, id="numeric string bpm"),
        pytest.param({"op": "set_bpm", "segment": 0, "bpm": False}, id="bool bpm"),
        pytest.param({"op": "set_bpm", "segment": 0, "bpm": 90.0, "anchor_ms": 2100.0}, id="bpm with an anchor"),
        pytest.param({"op": "split", "at_ms": "6000"}, id="numeric string split"),
        pytest.param({"op": "split", "at_ms": True}, id="bool split"),
        pytest.param({"op": "split", "at_ms": 6000.0, "segment": 0}, id="split with a segment"),
        pytest.param({"op": "merge", "segment": "0"}, id="numeric string merge"),
        pytest.param({"op": "merge", "segment": 0, "at_ms": 6000.0}, id="merge with a time"),
        pytest.param({"op": "match", "segment": 1}, id="match without a side"),
        pytest.param({"op": "match", "segment": 1, "side": "before"}, id="match with an unknown side"),
        pytest.param({"op": "match", "segment": 1, "side": "previous", "bpm": 120.0}, id="match with a bpm"),
    ],
)
def test_bad_patch_body_is_422(client: TestClient, settings: Settings, body: dict) -> None:
    job_id = write_done_job(settings, make_multi_report())
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, body)
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    "template",
    [
        '{"op": "set_anchor", "segment": 0, "anchor_ms": %s}',
        '{"op": "set_bpm", "segment": 0, "bpm": %s}',
        '{"op": "split", "at_ms": %s}',
    ],
    ids=["set_anchor", "set_bpm", "split"],
)
def test_nan_and_infinity_are_422(settings: Settings, template: str, literal: str) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    # a real client only sees the response, so the test client shouldn't re-raise a server error
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        # raw body, the json encoder refuses to write these
        resp = client.patch(f"/api/jobs/{job_id}/report", content=(template % literal).encode(), headers=JSON_HEADERS)
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("job_id", [uuid.uuid4().hex, "not-a-job"])
def test_unknown_job_is_404_on_the_edit_routes(client: TestClient, settings: Settings, job_id: str) -> None:
    # a real job sits next to it, so a stray write into the wrong folder would show
    write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    assert patch_anchor(client, job_id, 2100.0).status_code == 404
    for suffix in ("beats", "audio"):
        resp = client.get(f"/api/jobs/{job_id}/{suffix}")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "job not found"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("body", EDIT_BODIES.values(), ids=EDIT_BODIES.keys())
@pytest.mark.parametrize(
    ("status", "stage", "error"),
    [
        ("queued", "queued", None),
        ("running", "tempo", None),
        ("failed", "failed", {"stage": "trim", "message": "audio is silent"}),
    ],
)
def test_patch_on_an_unfinished_job_is_409_and_writes_nothing(
    client: TestClient, settings: Settings, body: dict, status: str, stage: str, error: dict | None
) -> None:
    # written after startup, so recover() has already run and leaves them alone
    job_id = write_job_dir(settings, status, stage, error)
    # files are there on purpose, it's the status that has to stop the edit. a failed job has none, one that
    # failed a re-analysis still serves its last good report, see test_reanalysis_failure.py
    if status != "failed":
        add_files(settings, job_id, make_multi_report())
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, body)
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
    # a failed job has no files, same as above
    if status != "failed":
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
        responses = list(pool.map(lambda v: patch_anchor(client, job_id, v), values))
    assert [r.status_code for r in responses] == [200] * 20

    report = stored_report(settings, job_id)
    edits = [e.model_dump(mode="json") for e in report.edits]
    # the flip to manual is logged by whichever request got there first, and only by that one. its entry
    # is the segment's with the anchor inside, the other 19 are the anchor alone
    assert [e["field"] for e in edits] == ["tempo_map/0"] + ["tempo_map/0/anchor_ms"] * 19
    first = flat(edits[0])
    assert set(first) == {"tempo_map/0/anchor_ms", "tempo_map/0/confidence", "tempo_map/0/source"}
    assert first["tempo_map/0/confidence"] == (1.0, None)
    assert first["tempo_map/0/source"] == ("auto", "manual")
    moves = [flat(e)["tempo_map/0/anchor_ms"] for e in edits]
    assert sorted(new for _, new in moves) == values
    # a read-modify-write that lost an update would break the chain here
    assert moves[0][0] == 2000.0
    for earlier, later in zip(moves, moves[1:]):
        assert later[0] == earlier[1]
    assert report.tempo_map[0].anchor_ms == moves[-1][1]
    assert client.get(f"/api/jobs/{job_id}/report").json() == report.model_dump(mode="json")


# --- set_bpm ---


def test_set_bpm_changes_one_segment_and_logs_the_flip_to_manual(client: TestClient, settings: Settings) -> None:
    original = make_multi_report()
    job_id = write_done_job(settings, original)

    resp = patch_bpm(client, job_id, 90.0, segment=1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    (edit,) = body["edits"]
    assert edit["field"] == "tempo_map/1"
    assert edit["old"] == {"bpm": 60.0, "confidence": 1.0, "source": "auto"}
    assert edit["new"] == {"bpm": 90.0, "confidence": None, "source": "manual"}
    # the grid is rebuilt around the same anchor and the edges stay
    assert TimingReport.model_validate(body).tempo_map == [
        original.tempo_map[0],
        make_segment(8000.0, 14000.0, bpm=90.0, anchor_ms=8020.0, confidence=None, source="manual"),
        original.tempo_map[2],
    ]
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


def test_bpm_is_rounded_to_six_decimals(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    resp = patch_bpm(client, job_id, 100.12345678)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tempo_map"][0]["bpm"] == 100.123457
    assert changes(resp.json()["edits"])["tempo_map/0/bpm"] == (120.0, 100.123457)


def test_doubling_then_halving_the_bpm_lands_back_exactly(client: TestClient, settings: Settings) -> None:
    # four decimals like the analysis writes, rounding any coarser would drift on the way back
    bpm = 117.1234
    job_id = write_done_job(settings, make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, bpm=bpm, anchor_ms=2010.0)]))

    doubled = patch_bpm(client, job_id, bpm * 2)
    assert doubled.status_code == 200, doubled.text
    assert doubled.json()["tempo_map"][0]["bpm"] == bpm * 2

    halved = patch_bpm(client, job_id, bpm * 2 / 2)
    assert halved.status_code == 200, halved.text
    segment = halved.json()["tempo_map"][0]
    assert segment["bpm"] == bpm
    assert segment["anchor_ms"] == 2010.0
    # the first entry is the segment's, it flipped to manual then
    bpm_edits = [flat(e)["tempo_map/0/bpm"] for e in halved.json()["edits"]]
    assert bpm_edits == [(bpm, bpm * 2), (bpm * 2, bpm)]
    assert stored_report(settings, job_id).tempo_map[0].bpm == bpm


@pytest.mark.parametrize("value", [1000.0, 0.000001], ids=["the largest", "the smallest that survives rounding"])
def test_bpm_inside_the_range_is_allowed(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)

    resp = patch_bpm(client, job_id, value)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tempo_map"][0]["bpm"] == value


def test_manual_bpm_goes_past_the_detection_range(client: TestClient, settings: Settings) -> None:
    # 60-320 is for detection only. a song charted at 440 is set by hand, by x2 or by typing it
    job_id = write_done_job(settings, make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, bpm=220.0)]))

    doubled = patch_bpm(client, job_id, 440.0)
    assert doubled.status_code == 200, doubled.text
    assert doubled.json()["tempo_map"][0]["bpm"] == 440.0
    # and a ratio button on top of that, 440 x 4/3
    resp = patch_bpm(client, job_id, 440.0 * 4.0 / 3.0)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tempo_map"][0]["bpm"] == round(440.0 * 4.0 / 3.0, 6)


@pytest.mark.parametrize("value", [0, 0.0, -0.5, -120.0, 1000.001, 1001, 1e9], ids=str)
def test_bpm_outside_the_range_is_422(client: TestClient, settings: Settings, value: float) -> None:
    job_id = write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    resp = patch_bpm(client, job_id, value)
    assert resp.status_code == 422, resp.text
    assert snapshot(settings.jobs_dir) == before


def test_a_bpm_that_rounds_to_zero_does_not_break_the_report(client: TestClient, settings: Settings) -> None:
    # 1e-7 is above zero, so the request is fine, and 0.0 once it's rounded to six decimals
    job_id = write_done_job(settings)

    resp = patch_bpm(client, job_id, 1e-7)
    assert resp.status_code == 422, resp.text
    assert "bpm" in resp.json()["detail"]
    # a refused edit leaves the stored report readable and as it was
    assert client.get(f"/api/jobs/{job_id}/report").status_code == 200
    assert stored_report(settings, job_id).tempo_map[0].bpm > 0


@pytest.mark.parametrize("index", [3, 99], ids=["one past the end", "far past the end"])
@pytest.mark.parametrize("make_body", SEGMENT_OPS.values(), ids=SEGMENT_OPS.keys())
def test_segment_index_out_of_range_is_422_with_the_edit_error(
    client: TestClient, settings: Settings, make_body, index: int
) -> None:
    job_id = write_done_job(settings, make_multi_report())
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, make_body(index))
    assert resp.status_code == 422, resp.text
    assert resp.json() == {"detail": f"no tempo segment {index}, there are 3"}
    assert snapshot(settings.jobs_dir) == before


# --- split and merge ---


def test_split_adds_a_segment_and_logs_the_whole_map(client: TestClient, settings: Settings) -> None:
    original = make_multi_report()
    job_id = write_done_job(settings, original, beats=False)

    resp = patch_split(client, job_id, 11000.1234)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    raw = body["tempo_map"]
    assert len(raw) == 4
    for left, right in zip(raw, raw[1:]):
        assert left["end_ms"] == right["start_ms"]
    assert (raw[0]["start_ms"], raw[-1]["end_ms"]) == (original.trim.start_ms, original.trim.end_ms)

    segments = TimingReport.model_validate(body).tempo_map
    # cut at the rounded time, and the neighbours are the segments they were
    assert segments[1].end_ms == segments[2].start_ms == 11000.123
    assert (segments[1].start_ms, segments[2].end_ms) == (8000.0, 14000.0)
    assert segments[1].source == segments[2].source == "manual"
    assert [segments[0], segments[3]] == [original.tempo_map[0], original.tempo_map[2]]

    (edit,) = body["edits"]
    assert edit["field"] == "tempo_map"
    assert len(edit["old"]) == 3
    assert len(edit["new"]) == 4
    assert edit["old"] == [s.model_dump(mode="json") for s in original.tempo_map]
    assert edit["new"] == raw
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


@pytest.mark.parametrize(
    ("at_ms", "message"),
    [
        (1000.0, "isn't inside any tempo segment"),
        (22000.0, "isn't inside any tempo segment"),
        (2000.0, "isn't inside any tempo segment"),
        (TRIM_END_MS, "isn't inside any tempo segment"),
        (8000.0, "isn't inside any tempo segment"),
        (2249.9, "half a beat"),
        (7750.1, "half a beat"),
        (8499.9, "half a beat"),
        (13500.1, "half a beat"),
        (14124.9, "half a beat"),
        (21375.1, "half a beat"),
    ],
    ids=[
        "before the map",
        "after the map",
        "on the map start",
        "on the map end",
        "on a boundary",
        "120 bpm, under half a beat from the start",
        "120 bpm, under half a beat from the end",
        "60 bpm, under half a beat from the start",
        "60 bpm, under half a beat from the end",
        "240 bpm, under half a beat from the start",
        "240 bpm, under half a beat from the end",
    ],
)
def test_split_outside_the_map_or_too_close_to_an_edge_is_422(
    client: TestClient, settings: Settings, at_ms: float, message: str
) -> None:
    job_id = write_done_job(settings, make_multi_report(), beats=False)
    before = snapshot(settings.jobs_dir)

    resp = patch_split(client, job_id, at_ms)
    assert resp.status_code == 422, resp.text
    assert message in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


# half a beat of each segment's own tempo: 250 ms at 120 bpm, 500 at 60, 125 at 240
@pytest.mark.parametrize("at_ms", [2250.0, 7750.0, 8500.0, 13500.0, 14125.0, 21375.0], ids=str)
def test_split_exactly_half_a_beat_from_an_edge_is_allowed(client: TestClient, settings: Settings, at_ms: float) -> None:
    job_id = write_done_job(settings, make_multi_report(), beats=False)

    resp = patch_split(client, job_id, at_ms)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["tempo_map"]) == 4
    assert at_ms in [s["start_ms"] for s in resp.json()["tempo_map"]]


def test_merge_joins_a_segment_with_the_next_and_logs_the_whole_map(client: TestClient, settings: Settings) -> None:
    original = make_multi_report()
    job_id = write_done_job(settings, original, beats=False)

    resp = patch_merge(client, job_id, 0)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    segments = TimingReport.model_validate(body).tempo_map
    assert len(segments) == 2
    assert segments[0].end_ms == segments[1].start_ms
    assert (segments[0].start_ms, segments[0].end_ms) == (2000.0, 14000.0)
    assert segments[0].source == "manual"
    # nothing to refit from, so the first segment's grid carries on
    assert (segments[0].bpm, segments[0].anchor_ms, segments[0].confidence) == (120.0, 2010.0, None)
    assert segments[1] == original.tempo_map[2]

    (edit,) = body["edits"]
    assert edit["field"] == "tempo_map"
    assert len(edit["old"]) == 3
    assert len(edit["new"]) == 2
    assert edit["old"] == [s.model_dump(mode="json") for s in original.tempo_map]
    assert edit["new"] == body["tempo_map"]
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


@pytest.mark.parametrize(
    ("side", "kept", "span"),
    [("previous", 0, (2000.0, 14000.0)), ("next", 2, (8000.0, TRIM_END_MS))],
    ids=["previous", "next"],
)
def test_match_takes_the_neighbours_grid_as_one_edit(
    client: TestClient, settings: Settings, side: str, kept: int, span: tuple[float, float]
) -> None:
    original = make_multi_report()
    job_id = write_done_job(settings, original)

    resp = patch_edit(client, job_id, {"op": "match", "segment": 1, "side": side})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    segments = TimingReport.model_validate(body).tempo_map
    assert len(segments) == 2
    matched = next(s for s in segments if s.start_ms == span[0])
    neighbour = original.tempo_map[kept]
    # the neighbour's grid as it was, nothing refit even with a beats file there
    assert (matched.bpm, matched.anchor_ms) == (neighbour.bpm, neighbour.anchor_ms)
    assert (matched.start_ms, matched.end_ms) == span
    assert (matched.source, matched.confidence) == ("manual", None)

    (edit,) = body["edits"]
    assert edit["field"] == "tempo_map"
    assert edit["old"] == [s.model_dump(mode="json") for s in original.tempo_map]
    assert edit["new"] == body["tempo_map"]
    assert stored_report(settings, job_id) == TimingReport.model_validate(body)


@pytest.mark.parametrize(("segment", "side"), [(0, "previous"), (2, "next")])
def test_match_without_that_neighbour_is_422(client: TestClient, settings: Settings, segment: int, side: str) -> None:
    job_id = write_done_job(settings, make_multi_report())
    before = snapshot(settings.jobs_dir)

    resp = patch_edit(client, job_id, {"op": "match", "segment": segment, "side": side})
    assert resp.status_code == 422, resp.text
    assert resp.json() == {"detail": f"segment {segment} has no {side} segment to match"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    ("make", "index"),
    [(make_report, 0), (make_multi_report, 2)],
    ids=["only segment", "last of three"],
)
def test_merging_the_last_segment_is_422(client: TestClient, settings: Settings, make, index: int) -> None:
    job_id = write_done_job(settings, make())
    before = snapshot(settings.jobs_dir)

    resp = patch_merge(client, job_id, index)
    assert resp.status_code == 422, resp.text
    assert f"segment {index} is the last one" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


def test_split_then_merge_refits_from_the_beats_file(client: TestClient, settings: Settings) -> None:
    # the stored 100 is off on purpose, only a refit from the beats can land on 120
    report = make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, bpm=100.0, anchor_ms=FIRST_BEAT_MS, confidence=0.8)])
    job_id = write_done_job(settings, report, beats=grid_beats(int((TRIM_END_MS - FIRST_BEAT_MS) / 500.0)))

    split = patch_split(client, job_id, 10000.0)
    assert split.status_code == 200, split.text
    left, right = split.json()["tempo_map"]
    assert (left["start_ms"], left["end_ms"], right["start_ms"], right["end_ms"]) == (2000.0, 10000.0, 10000.0, TRIM_END_MS)
    for half in (left, right):
        assert half["bpm"] == pytest.approx(120.0, abs=BPM_TOLERANCE)
        assert half["source"] == "manual"
        assert half["confidence"] is not None
    assert left["anchor_ms"] == pytest.approx(2000.0, abs=ANCHOR_TOLERANCE_MS)
    # beat 16 of the grid is the first downbeat on the right of the cut
    assert right["anchor_ms"] == pytest.approx(10000.0, abs=ANCHOR_TOLERANCE_MS)

    merged = patch_merge(client, job_id, 0)
    assert merged.status_code == 200, merged.text
    (segment,) = merged.json()["tempo_map"]
    assert segment["bpm"] == pytest.approx(120.0, abs=BPM_TOLERANCE)
    assert segment["anchor_ms"] == pytest.approx(2000.0, abs=ANCHOR_TOLERANCE_MS)
    assert (segment["start_ms"], segment["end_ms"]) == (2000.0, TRIM_END_MS)
    assert segment["source"] == "manual"
    assert segment["confidence"] is not None

    edits = merged.json()["edits"]
    assert [e["field"] for e in edits] == ["tempo_map", "tempo_map"]
    assert [(len(e["old"]), len(e["new"])) for e in edits] == [(1, 2), (2, 1)]
    assert edits[1]["old"] == edits[0]["new"]


def test_split_without_a_beats_file_keeps_the_grid(client: TestClient, settings: Settings) -> None:
    report = make_report([make_segment(FIRST_BEAT_MS, TRIM_END_MS, bpm=100.0, anchor_ms=FIRST_BEAT_MS, confidence=0.8)])
    job_id = write_done_job(settings, report, beats=False)

    resp = patch_split(client, job_id, 10000.0)
    assert resp.status_code == 200, resp.text
    left, right = resp.json()["tempo_map"]
    assert (left["bpm"], left["anchor_ms"], left["confidence"]) == (100.0, 2000.0, None)
    # the first line of the old 600 ms grid from the cut on, so no beat moves
    assert (right["bpm"], right["anchor_ms"], right["confidence"]) == (100.0, 10400.0, None)
    assert left["source"] == right["source"] == "manual"


# --- stored 1.1 and 1.0 reports ---


def test_stored_1_1_report_is_served_as_2_5(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    old = make_report_1_1()
    path = settings.jobs_dir / job_id / "report.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    resp = client.get(f"/api/jobs/{job_id}/report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == "2.5"
    assert "beat_offset_ms" not in body
    assert body["tempo_map"] == [
        {
            "start_ms": 2000.0,
            "end_ms": TRIM_END_MS,
            "bpm": 120.0,
            "anchor_ms": 2120.5,
            "confidence": 1.0,
            "source": "auto",
            "ratio_merged": [],
        }
    ]
    assert body["tempo_map"][0]["anchor_ms"] == old["beat_offset_ms"]
    assert body["tempo_map"][0]["end_ms"] == old["trim"]["end_ms"]
    assert body["edits"] == old["edits"]
    assert body["source"] == old["source"]
    # reading never rewrites the file
    assert json.loads(path.read_text(encoding="utf-8")) == old


def test_patch_on_a_stored_1_1_report_writes_2_5(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    old = make_report_1_1()
    path = settings.jobs_dir / job_id / "report.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    resp = patch_anchor(client, job_id, 2130.0)
    assert resp.status_code == 200, resp.text
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == "2.5"
    assert "beat_offset_ms" not in on_disk
    assert stored_report(settings, job_id) == TimingReport.model_validate(resp.json())
    # the old entry stays first and untouched, the old offset is the anchor's old value
    assert on_disk["edits"][0] == old["edits"][0]
    assert changes(resp.json()["edits"][1:]) == {
        "tempo_map/0/anchor_ms": (2120.5, 2130.0),
        "tempo_map/0/source": ("auto", "manual"),
        "tempo_map/0/confidence": (1.0, None),
    }


def test_stored_1_1_beats_file_is_served_as_2_5(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    old = json.loads(make_beats().model_dump_json())
    old["schema_version"] = "1.1"
    del old["octave"]
    (settings.jobs_dir / job_id / "beats.json").write_text(json.dumps(old), encoding="utf-8")

    resp = client.get(f"/api/jobs/{job_id}/beats")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {**old, "schema_version": "2.5", "octave": "kept"}


def test_schema_1_0_report_is_409_for_get_and_patch(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)
    old = make_report_1_1()
    old["schema_version"] = "1.0"
    del old["source"]["codec"]
    del old["source"]["decoder_padding_samples"]
    (settings.jobs_dir / job_id / "report.json").write_text(json.dumps(old), encoding="utf-8")
    before = snapshot(settings.jobs_dir)

    for resp in (client.get(f"/api/jobs/{job_id}/report"), patch_anchor(client, job_id, 2100.0)):
        assert resp.status_code == 409
        assert "upload the file again" in resp.json()["detail"]
    assert snapshot(settings.jobs_dir) == before


# --- job list ---


def test_job_list_is_empty_without_jobs(client: TestClient) -> None:
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_jobs_are_listed_newest_first(client: TestClient, settings: Settings) -> None:
    # written out of order with random ids, so only created_at can put them right
    stamps = {
        "middle": "2026-03-02T09:00:00.000+00:00",
        "oldest": "2026-03-01T23:59:59.999+00:00",
        "newest": "2026-03-02T09:00:00.001+00:00",
    }
    ids = {name: write_job_dir(settings, "done", "done", created_at=stamp) for name, stamp in stamps.items()}

    resp = client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    assert [job["job_id"] for job in resp.json()] == [ids["newest"], ids["middle"], ids["oldest"]]


def test_job_summary_has_the_stored_fields_and_the_status(client: TestClient, settings: Settings) -> None:
    error = {"stage": "trim", "message": "audio is silent"}
    job_id = write_job_dir(settings, "failed", "failed", error, created_at="2026-03-01T09:00:00.000+00:00", sha256=SHA_A)

    resp = client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "job_id": job_id,
            "filename": "song.mp3",
            "sha256": SHA_A,
            "size_bytes": 1,
            "created_at": "2026-03-01T09:00:00.000+00:00",
            # never re-analyzed
            "reanalyzed_at": None,
            "status": "failed",
            "edits": None,
        }
    ]


def test_sha256_filter_lists_only_that_files_jobs(client: TestClient, settings: Settings) -> None:
    older_a = write_job_dir(settings, "done", "done", created_at="2026-03-01T09:00:00.000+00:00", sha256=SHA_A)
    only_b = write_job_dir(settings, "done", "done", created_at="2026-03-02T09:00:00.000+00:00", sha256=SHA_B)
    newer_a = write_job_dir(settings, "queued", "queued", created_at="2026-03-03T09:00:00.000+00:00", sha256=SHA_A)

    def listed(**params) -> list[str]:
        resp = client.get("/api/jobs", params=params)
        assert resp.status_code == 200, resp.text
        return [job["job_id"] for job in resp.json()]

    assert listed(sha256=SHA_A) == [newer_a, older_a]
    assert listed(sha256=SHA_B) == [only_b]
    assert listed(sha256="c" * 64) == []
    assert listed() == [newer_a, only_b, older_a]


@pytest.mark.parametrize(
    "sha256",
    ["abc", "A" * 64, "g" * 64, "a" * 63, "a" * 65, ""],
    ids=["too short", "upper case", "not hex", "one short", "one long", "empty"],
)
def test_bad_sha256_filter_is_422(client: TestClient, settings: Settings, sha256: str) -> None:
    write_job_dir(settings, "done", "done")

    resp = client.get("/api/jobs", params={"sha256": sha256})
    assert resp.status_code == 422, resp.text


def test_summary_counts_the_edits_in_the_report(client: TestClient, settings: Settings) -> None:
    stamp = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
    edited = make_report().model_copy(
        update={
            "edits": [
                Edit(field="tempo_map/0/bpm", old=120.0, new=90.0, timestamp=stamp),
                Edit(field="tempo_map/0/bpm", old=90.0, new=100.0, timestamp=stamp),
            ]
        }
    )
    expected: dict[str, int | None] = {}
    expected[write_done_job(settings, edited)] = 2
    expected[write_done_job(settings)] = 0
    # no report to count: still queued, or done with the file gone
    expected[write_job_dir(settings, "queued", "queued")] = None
    expected[write_job_dir(settings, "done", "done")] = None

    # counted after the upgrade
    in_1_1 = write_done_job(settings)
    (settings.jobs_dir / in_1_1 / "report.json").write_text(json.dumps(make_report_1_1()), encoding="utf-8")
    expected[in_1_1] = 1

    # can't be read any more, so there's nothing to count
    in_1_0 = write_done_job(settings)
    old = make_report_1_1()
    old["schema_version"] = "1.0"
    del old["source"]["codec"]
    del old["source"]["decoder_padding_samples"]
    (settings.jobs_dir / in_1_0 / "report.json").write_text(json.dumps(old), encoding="utf-8")
    expected[in_1_0] = None

    resp = client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    assert {job["job_id"]: job["edits"] for job in resp.json()} == expected


JOB_JSON = json.dumps({"job_id": "0" * 32, "filename": "song.mp3", "sha256": "0" * 64, "size_bytes": 1, "created_at": CREATED_AT})
STATUS_JSON = json.dumps({"status": "done", "stage": "done", "error": None, "updated_at": CREATED_AT})


@pytest.mark.parametrize(
    "files",
    [
        pytest.param({}, id="empty folder"),
        # what a crash in the middle of an upload leaves behind
        pytest.param({"job.json": JOB_JSON}, id="no status.json"),
        pytest.param({"status.json": STATUS_JSON}, id="no job.json"),
        pytest.param({"job.json": "{not json", "status.json": STATUS_JSON}, id="broken job.json"),
    ],
)
def test_folders_that_are_not_finished_uploads_are_left_out_of_the_list(
    client: TestClient, settings: Settings, files: dict[str, str]
) -> None:
    good = write_job_dir(settings, "done", "done")
    stray = settings.jobs_dir / uuid.uuid4().hex
    stray.mkdir()
    for name, text in files.items():
        (stray / name).write_text(text, encoding="utf-8")

    resp = client.get("/api/jobs")
    assert resp.status_code == 200, resp.text
    assert [job["job_id"] for job in resp.json()] == [good]


# --- reanalyze ---


@pytest.mark.parametrize(("status", "stage"), [("queued", "queued"), ("running", "beats")])
def test_reanalyze_is_409_while_the_job_is_unfinished(client: TestClient, settings: Settings, status: str, stage: str) -> None:
    job_id = write_job_dir(settings, status, stage)
    # the upload is there on purpose, it's the status that has to stop it
    (settings.jobs_dir / job_id / "original.wav").write_bytes(b"x")
    before = snapshot(settings.jobs_dir)

    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 409
    assert resp.json() == {"detail": f"job is still at {stage}"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize("job_id", [uuid.uuid4().hex, "not-a-job"])
def test_reanalyze_unknown_job_is_404(client: TestClient, settings: Settings, job_id: str) -> None:
    write_done_job(settings)
    before = snapshot(settings.jobs_dir)

    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "job not found"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    ("status", "stage", "error"),
    [("done", "done", None), ("failed", "failed", {"stage": "beats", "message": "boom"})],
    ids=["done", "failed"],
)
def test_reanalyze_without_the_original_is_409(
    client: TestClient, settings: Settings, status: str, stage: str, error: dict | None
) -> None:
    job_id = write_job_dir(settings, status, stage, error)
    add_files(settings, job_id)
    before = snapshot(settings.jobs_dir)

    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "the original upload is missing, upload the file again"}
    assert snapshot(settings.jobs_dir) == before


@pytest.mark.parametrize(
    ("status", "stage", "error"),
    [("done", "done", None), ("failed", "failed", {"stage": "beats", "message": "boom"})],
    ids=["done", "failed"],
)
def test_reanalyze_queues_a_finished_job(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch, status: str, stage: str, error: dict | None
) -> None:
    submitted: list[str] = []
    # the analysis itself is covered by the ffmpeg tests, this is only about the hand-off
    monkeypatch.setattr(JobRunner, "submit", lambda self, job_id: submitted.append(job_id))
    job_id = write_job_dir(settings, status, stage, error)
    (settings.jobs_dir / job_id / "original.wav").write_bytes(b"x")

    resp = client.post(f"/api/jobs/{job_id}/reanalyze")
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"job_id": job_id}
    assert submitted == [job_id]
    assert client.get(f"/api/jobs/{job_id}").json() == {
        "status": "queued",
        "stage": "queued",
        "error": None,
        "report_available": False,
    }


# --- beats and audio ---


def test_beats_returns_the_beats_file(client: TestClient, settings: Settings) -> None:
    job_id = write_done_job(settings)

    resp = client.get(f"/api/jobs/{job_id}/beats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tracker"] == "madmom"
    assert body["octave"] == "kept"
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

    segment = client.get(f"/api/jobs/{job_id}/report").json()["tempo_map"][0]
    analysed = segment["anchor_ms"]

    resp = patch_anchor(client, job_id, analysed + 1.0)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert changes(body["edits"]) == {
        "tempo_map/0/anchor_ms": (analysed, round(analysed + 1.0, 3)),
        "tempo_map/0/source": ("auto", "manual"),
        "tempo_map/0/confidence": (segment["confidence"], None),
    }
    assert body["tempo_map"][0]["anchor_ms"] == round(analysed + 1.0, 3)
    assert client.get(f"/api/jobs/{job_id}/report").json() == body

    audio = client.get(f"/api/jobs/{job_id}/audio")
    assert audio.status_code == 200
    assert audio.content == (settings.jobs_dir / job_id / "decoded.wav").read_bytes()

    beats = client.get(f"/api/jobs/{job_id}/beats")
    assert beats.status_code == 200
    assert len(beats.json()["beats"]) == 40
    assert beats.json()["tracker"] in ("madmom", "librosa")
    assert beats.json()["octave"] == "kept"
