"""Beat offset and bpm through the whole pipeline, on click tracks with known ground truth."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.analysis.pipeline import AnalysisConfig, run_analysis
from tests.synth import ClickTrackSpec, cached_click_wav

OFFSET_TOLERANCE_MS = 5.0
BPM_TOLERANCE = 0.01

ENCODES = {
    "wav": None,
    "mp3": ("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "m4a": ("m4a", ["-c:a", "aac", "-b:a", "192k"]),
}


def _source(tmp_path: Path, spec: ClickTrackSpec, encode: str) -> tuple[Path, np.ndarray]:
    wav, track = cached_click_wav(spec)
    if ENCODES[encode] is None:
        src = tmp_path / "song.wav"
        shutil.copy(wav, src)
    else:
        ext, args = ENCODES[encode]
        src = tmp_path / f"song.{ext}"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), *args, str(src)],
            check=True,
        )
    return src, track


def _analyze(tmp_path: Path, spec: ClickTrackSpec, encode: str = "wav", tracker: str = "auto"):
    src, track = _source(tmp_path, spec, encode)
    work = tmp_path / "work"
    work.mkdir()
    out = run_analysis(src, work, filename=src.name, sha256="0" * 64, config=AnalysisConfig(tracker=tracker))
    return out, track


CASES = [
    # (spec, encode)
    pytest.param(ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True), "wav", id="120bpm-137.5ms"),
    pytest.param(ClickTrackSpec(bpm=174, lead_silence_s=1.234567, accent_downbeats=True), "wav", id="174bpm-1234.567ms"),
    pytest.param(ClickTrackSpec(bpm=128.4, lead_silence_s=0.0875, accent_downbeats=True, sample_rate=48000), "wav", id="128.4bpm-87.5ms-48k"),
    pytest.param(ClickTrackSpec(bpm=90, lead_silence_s=2.00325, accent_downbeats=True), "wav", id="90bpm-2003.25ms"),
    pytest.param(ClickTrackSpec(bpm=200, lead_silence_s=0.0413, accent_downbeats=True, beats=64), "wav", id="200bpm-41.3ms"),
    pytest.param(ClickTrackSpec(bpm=87.5, lead_silence_s=0.5, accent_downbeats=True, beats_per_bar=3), "wav", id="87.5bpm-3-4"),
    pytest.param(
        ClickTrackSpec(bpm=150, lead_silence_s=0.3333, accent_downbeats=True, noise_floor_db=-90.0), "wav", id="150bpm-noise90"
    ),
    pytest.param(ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True), "mp3", id="120bpm-137.5ms-mp3"),
    pytest.param(
        ClickTrackSpec(bpm=174, lead_silence_s=0.6125, accent_downbeats=True, sample_rate=48000), "mp3", id="174bpm-48k-mp3"
    ),
    pytest.param(ClickTrackSpec(bpm=140, lead_silence_s=0.25, accent_downbeats=True), "m4a", id="140bpm-m4a"),
]


@pytest.mark.ffmpeg
@pytest.mark.parametrize(("spec", "encode"), CASES)
def test_madmom_recovers_offset_and_bpm(tmp_path, spec, encode):
    pytest.importorskip("madmom", reason="madmom not installed, the librosa fallback has its own test", exc_type=ImportError)
    out, track = _analyze(tmp_path, spec, encode)
    report = out.report
    truth = float(track.downbeats_ms[0])

    assert out.tracked.tracker == "madmom"
    assert report.beat_offset_ms is not None
    assert abs(report.beat_offset_ms - truth) <= OFFSET_TOLERANCE_MS, f"offset {report.beat_offset_ms:.3f}, truth {truth:.3f}"
    assert abs(report.tempo_map[0].bpm - spec.bpm) <= BPM_TOLERANCE, f"bpm {report.tempo_map[0].bpm:.4f}"
    assert report.tempo_map[0].confidence == 1.0


@pytest.mark.ffmpeg
def test_snap_removes_the_madmom_frame_bias(tmp_path):
    # milestone 1 saw madmom's beats a frame (10 ms) early on clicks, snap is what fixes it
    pytest.importorskip("madmom", exc_type=ImportError)
    out, track = _analyze(tmp_path, ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True))

    raw = out.tracked.times_ms - track.onsets_ms
    snapped = out.snap.times_ms - track.onsets_ms

    assert -20.0 < raw.mean() < -5.0
    assert np.all(np.abs(snapped) <= 1.5)
    assert out.snap.snapped.all()


@pytest.mark.ffmpeg
def test_pickup_beats_dont_move_the_offset(tmp_path):
    pytest.importorskip("madmom", exc_type=ImportError)
    spec = ClickTrackSpec(bpm=120, lead_silence_s=0.75, accent_downbeats=True, pickup_beats=2, beats=42)
    out, track = _analyze(tmp_path, spec)

    # the offset is the first downbeat, the two pickup clicks come before it
    assert abs(out.report.beat_offset_ms - track.downbeats_ms[0]) <= OFFSET_TOLERANCE_MS
    assert track.downbeats_ms[0] > track.onsets_ms[0]
    assert out.fit.indices[0] == -2

    # pickup bar is bar 0, so the first downbeat starts bar 1
    beats = out.beats.beats
    assert [(b.bar, b.beat_in_bar) for b in beats[:4]] == [(0, 3), (0, 4), (1, 1), (1, 2)]
    assert beats[2].is_downbeat


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    "spec",
    [
        pytest.param(ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True), id="120bpm-137.5ms"),
        pytest.param(ClickTrackSpec(bpm=174, lead_silence_s=1.234567, accent_downbeats=True), id="174bpm-1234.567ms"),
    ],
)
def test_librosa_fallback_recovers_offset_and_bpm_with_lower_confidence(tmp_path, spec):
    # the first click is a downbeat here, which is the one case where librosa's guess is right
    out, track = _analyze(tmp_path, spec, tracker="librosa")
    report = out.report

    assert out.beats.tracker == "librosa"
    assert abs(report.beat_offset_ms - track.downbeats_ms[0]) <= OFFSET_TOLERANCE_MS
    assert abs(report.tempo_map[0].bpm - spec.bpm) <= BPM_TOLERANCE
    assert report.tempo_map[0].confidence is not None
    assert report.tempo_map[0].confidence <= 0.5
