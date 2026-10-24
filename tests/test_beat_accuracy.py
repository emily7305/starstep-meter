"""First downbeat, bpm and tempo changes through the whole pipeline, on click tracks with known ground truth."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from backend.analysis import pipeline
from backend.analysis.beats import TrackedBeats
from backend.analysis.pipeline import AnalysisConfig, run_analysis
from backend.analysis.tempo_edit import set_bpm, split
from backend.schema.models import Edit
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


def _analyze(tmp_path: Path, spec: ClickTrackSpec, encode: str = "wav", tracker: str = "auto", previous=None):
    src, track = _source(tmp_path, spec, encode)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    out = run_analysis(src, work, filename=src.name, sha256="0" * 64, config=AnalysisConfig(tracker=tracker), previous=previous)
    return out, track


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed, the librosa fallback has its own tests", exc_type=ImportError)


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
    # past the old 240 ceiling. at these leads madmom's network tracks every other click and
    # the octave check has to double it back, see docs/decisions.md
    pytest.param(ClickTrackSpec(bpm=250, beats=96, lead_silence_s=1.2031, accent_downbeats=True), "wav", id="250bpm"),
    pytest.param(ClickTrackSpec(bpm=270, beats=96, lead_silence_s=0.4375, accent_downbeats=True), "wav", id="270bpm"),
    pytest.param(ClickTrackSpec(bpm=300, beats=96, lead_silence_s=1.2031, accent_downbeats=True), "wav", id="300bpm"),
    pytest.param(ClickTrackSpec(bpm=270, beats=96, lead_silence_s=0.3125, accent_downbeats=True), "mp3", id="270bpm-mp3"),
]


@pytest.mark.ffmpeg
@pytest.mark.parametrize(("spec", "encode"), CASES)
@pytest.mark.usefixtures("madmom")
def test_madmom_recovers_first_downbeat_and_bpm(tmp_path, spec, encode):
    out, track = _analyze(tmp_path, spec, encode)
    report = out.report
    truth = float(track.downbeats_ms[0])
    first = report.tempo_map[0]

    assert out.tracked.tracker == "madmom"
    assert len(report.tempo_map) == 1
    assert abs(first.anchor_ms - truth) <= OFFSET_TOLERANCE_MS, f"first downbeat {first.anchor_ms:.3f}, truth {truth:.3f}"
    assert abs(first.bpm - spec.bpm) <= BPM_TOLERANCE, f"bpm {first.bpm:.4f}"
    assert first.confidence == 1.0


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_snap_removes_the_madmom_frame_bias(tmp_path):
    # milestone 1 saw madmom's beats a frame (10 ms) early on clicks, the bias shift and snap fix it
    out, track = _analyze(tmp_path, ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True))

    raw = out.tracked.times_ms - track.onsets_ms
    snapped = out.snap.times_ms - track.onsets_ms

    assert -20.0 < raw.mean() < -5.0
    assert np.all(np.abs(snapped) <= 1.5)
    assert out.snap.snapped.all()


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_pickup_beats_dont_move_the_first_downbeat(tmp_path):
    spec = ClickTrackSpec(bpm=120, lead_silence_s=0.75, accent_downbeats=True, pickup_beats=2, beats=42)
    out, track = _analyze(tmp_path, spec)

    # the anchor is the first downbeat, the two pickup clicks come before it
    assert abs(out.report.tempo_map[0].anchor_ms - track.downbeats_ms[0]) <= OFFSET_TOLERANCE_MS
    assert track.downbeats_ms[0] > track.onsets_ms[0]
    assert out.tempo.indices[0] == -2

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
        pytest.param(ClickTrackSpec(bpm=250, beats=96, lead_silence_s=0.4375, accent_downbeats=True), id="250bpm"),
        pytest.param(ClickTrackSpec(bpm=270, beats=96, lead_silence_s=0.4375, accent_downbeats=True), id="270bpm"),
        pytest.param(ClickTrackSpec(bpm=300, beats=96, lead_silence_s=0.4375, accent_downbeats=True), id="300bpm"),
    ],
)
def test_librosa_fallback_recovers_first_downbeat_and_bpm_with_lower_confidence(tmp_path, spec):
    # the first click is a downbeat here, which is the one case where librosa's guess is right
    out, track = _analyze(tmp_path, spec, tracker="librosa")
    report = out.report

    assert out.beats.tracker == "librosa"
    assert len(report.tempo_map) == 1
    assert abs(report.tempo_map[0].anchor_ms - track.downbeats_ms[0]) <= OFFSET_TOLERANCE_MS
    assert abs(report.tempo_map[0].bpm - spec.bpm) <= BPM_TOLERANCE
    assert report.tempo_map[0].confidence is not None
    assert report.tempo_map[0].confidence <= 0.5


# --- tempo maps ---

TEMPO_CHANGES = [
    pytest.param(
        ClickTrackSpec(bpm=150, beats=160, lead_silence_s=0.7313, accent_downbeats=True, tempo_changes=((64, 200.0),)),
        "wav",
        id="150-200",
    ),
    pytest.param(
        ClickTrackSpec(bpm=174, beats=192, lead_silence_s=1.1171, accent_downbeats=True, tempo_changes=((96, 128.0),)),
        "mp3",
        id="174-128-mp3",
    ),
    pytest.param(
        ClickTrackSpec(bpm=128, beats=200, lead_silence_s=1.2071, accent_downbeats=True, tempo_changes=((64, 192.0), (160, 128.0))),
        "wav",
        id="128-192-128",
    ),
    pytest.param(
        ClickTrackSpec(
            bpm=140, beats=240, lead_silence_s=0.2519, accent_downbeats=True, sample_rate=48000, tempo_changes=((64, 180.0), (128, 210.0))
        ),
        "wav",
        id="140-180-210-48k",
    ),
]


def _bpms(spec):
    return [spec.bpm, *(bpm for _, bpm in sorted(spec.tempo_changes))]


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
@pytest.mark.parametrize(("spec", "encode"), TEMPO_CHANGES)
def test_tempo_changes_land_within_a_beat_with_each_bpm_right(tmp_path, spec, encode):
    out, track = _analyze(tmp_path, spec, encode)
    segments = out.report.tempo_map
    bpms = _bpms(spec)

    assert [round(s.bpm) for s in segments] == [round(b) for b in bpms]
    for seg, bpm in zip(segments, bpms):
        assert abs(seg.bpm - bpm) <= BPM_TOLERANCE, f"bpm {seg.bpm:.4f}, truth {bpm}"
        assert seg.source == "auto"
        assert seg.confidence == 1.0
    for seg, change, bpm in zip(segments[1:], track.change_ms, bpms[1:]):
        assert abs(seg.start_ms - change) < 60000.0 / bpm, f"change at {seg.start_ms:.3f}, truth {change:.3f}"
        # within a beat is the requirement, on clicks it's the snap's 0.7 ms
        assert abs(seg.start_ms - change) <= OFFSET_TOLERANCE_MS
    assert segments[0].anchor_ms == pytest.approx(track.downbeats_ms[0], abs=OFFSET_TOLERANCE_MS)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("tracker", ["madmom", "librosa"])
@pytest.mark.parametrize("bpm", [128.0, 270.0])
def test_steady_track_with_small_jitter_is_one_segment(tmp_path, tracker, bpm):
    if tracker == "madmom":
        pytest.importorskip("madmom", exc_type=ImportError)
    spec = ClickTrackSpec(bpm=bpm, beats=int(bpm), lead_silence_s=0.5531, accent_downbeats=True, jitter_ms=2.0, seed=4)
    out, _ = _analyze(tmp_path, spec, tracker=tracker)

    assert len(out.report.tempo_map) == 1
    assert out.report.tempo_map[0].bpm == pytest.approx(bpm, abs=0.05)


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_reanalysis_leaves_a_manual_segment_untouched(tmp_path):
    spec = ClickTrackSpec(bpm=128, beats=200, lead_silence_s=1.2071, accent_downbeats=True, tempo_changes=((64, 192.0), (160, 128.0)))
    first, track = _analyze(tmp_path, spec)
    auto = first.report.tempo_map
    assert len(auto) == 3

    # a hand edit that doesn't line up with what analysis finds: the middle segment split in two
    # and the second half set to double time
    mid = (auto[1].start_ms + auto[1].end_ms) / 2.0
    edited = split(auto, mid)
    edited = set_bpm(edited, 2, edited[2].bpm * 2.0)
    edit = Edit(field="tempo_map/2/bpm", old=auto[1].bpm, new=edited[2].bpm, timestamp="2026-10-24T12:00:00+00:00")
    previous = first.report.model_copy(update={"tempo_map": edited, "edits": [edit]})

    again, _ = _analyze(tmp_path, spec, previous=previous)
    tempo_map = again.report.tempo_map

    manual = [s for s in tempo_map if s.source == "manual"]
    assert manual == [s for s in edited if s.source == "manual"]
    assert again.report.edits == previous.edits
    # the auto parts are fresh and fill the rest, the map still covers the trimmed region
    assert tempo_map[0].source == "auto" and tempo_map[0].bpm == pytest.approx(128.0, abs=BPM_TOLERANCE)
    assert tempo_map[-1].source == "auto" and tempo_map[-1].bpm == pytest.approx(128.0, abs=BPM_TOLERANCE)
    assert tempo_map[0].start_ms == again.report.trim.start_ms
    assert tempo_map[-1].end_ms == again.report.trim.end_ms


@pytest.mark.ffmpeg
def test_pipeline_shifts_madmom_beats_before_snapping(tmp_path, monkeypatch):
    # stands in for madmom with beats 18-25 ms early, past what the 20 ms window reaches alone
    spec = ClickTrackSpec(bpm=140, beats=64, lead_silence_s=0.8, accent_downbeats=True)
    _, track = cached_click_wav(spec)
    early = track.onsets_ms - np.random.default_rng(9).uniform(18.0, 25.0, len(track.onsets_ms))

    def fake_track(*_args, **_kwargs):
        positions = np.arange(len(early)) % 4 + 1
        return TrackedBeats(times_ms=early, positions=positions, tracker="madmom", downbeats_known=True)

    monkeypatch.setattr(pipeline, "track_beats", fake_track)
    out, _ = _analyze(tmp_path, spec)

    assert out.snap.snapped.all()
    assert np.abs(out.snap.times_ms - track.onsets_ms).max() <= 1.5
    assert out.report.tempo_map[0].bpm == pytest.approx(140.0, abs=BPM_TOLERANCE)
