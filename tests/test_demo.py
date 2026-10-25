"""The demo track: generated in code, analyzed like an upload, kept out of the way of real songs."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.analysis.pipeline import run_analysis
from backend.api.app import create_app
from backend.api.demo import DEMO_BPM, DEMO_LEAD_S, DEMO_NAME, SAMPLE_RATE, demo_samples, write_demo
from backend.api.settings import Settings
from tests.test_reanalysis_failure import fake_analysis, succeeds, wait_for_job


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "data", retention_days=0))) as c:
        yield c


def test_the_demo_is_the_same_every_time_and_starts_after_its_lead():
    a, b = demo_samples(), demo_samples()
    assert np.array_equal(a, b)
    assert np.max(np.abs(a)) == pytest.approx(10 ** (-3 / 20), rel=1e-6)
    lead = int(DEMO_LEAD_S * SAMPLE_RATE)
    assert np.all(a[:lead] == 0.0)
    assert np.abs(a[lead:lead + 200]).max() > 0.1


@pytest.mark.ffmpeg
def test_a_demo_job_is_marked_and_a_new_one_replaces_the_old(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_analysis(monkeypatch, succeeds)
    first = client.post("/api/demo").json()["job_id"]
    assert wait_for_job(client, first)["status"] == "done"
    (listed,) = client.get("/api/jobs").json()
    assert (listed["job_id"], listed["filename"], listed["demo"]) == (first, DEMO_NAME, True)

    second = client.post("/api/demo").json()["job_id"]
    assert wait_for_job(client, second)["status"] == "done"
    assert [j["job_id"] for j in client.get("/api/jobs").json()] == [second]
    assert client.get(f"/api/jobs/{first}").status_code == 404


@pytest.mark.ffmpeg
def test_the_demo_analyzes_to_its_own_grid():
    pytest.importorskip("madmom", reason="madmom not installed", exc_type=ImportError)
    with tempfile.TemporaryDirectory() as tmp:
        path = write_demo(Path(tmp) / DEMO_NAME)
        out = run_analysis(path, Path(tmp), filename=DEMO_NAME, sha256="0" * 64)
    (seg,) = out.report.tempo_map
    assert seg.bpm == pytest.approx(DEMO_BPM, abs=0.01)
    # the first kick, within the snap's 0.7 ms and a little
    assert seg.anchor_ms == pytest.approx(1000.0 * DEMO_LEAD_S, abs=2.0)
    assert [(m.numerator, m.denominator) for m in out.report.meter_map] == [(4, 4)]
