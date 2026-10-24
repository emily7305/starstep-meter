import hashlib
import shutil

import numpy as np
import pytest
import soundfile as sf

from backend.analysis.pipeline import StageError, run_analysis
from backend.schema.models import TimingReport
from tests.synth import ClickTrackSpec, cached_click_wav


def _copy_wav(tmp_path, spec: ClickTrackSpec):
    # run on a copy, the cached fixture stays where the other tests expect it
    cached, track = cached_click_wav(spec)
    src = tmp_path / "song.wav"
    shutil.copy(cached, src)
    return src, track


@pytest.mark.ffmpeg
def test_run_analysis_builds_the_milestone_1_report(tmp_path):
    src, track = _copy_wav(tmp_path, ClickTrackSpec(bpm=120, lead_silence_s=2.0))
    sha256 = hashlib.sha256(src.read_bytes()).hexdigest()
    work = tmp_path / "work"
    work.mkdir()
    stages = []

    out = run_analysis(src, work, filename="song.wav", sha256=sha256, on_stage=stages.append)

    assert stages == ["decode", "trim", "tempo"]
    assert (work / "decoded.wav").exists()
    assert out.decoded.path == work / "decoded.wav"

    # survives a trip through json, so it's a valid report and not just a model instance
    report = TimingReport.model_validate_json(out.report.model_dump_json())
    assert report == out.report

    assert report.source.filename == "song.wav"
    assert report.source.sha256 == sha256
    assert report.source.sample_rate == 44100
    assert report.source.duration_ms == pytest.approx(track.duration_ms, abs=0.01)
    assert report.trim.start_ms == pytest.approx(track.content_start_ms, abs=10.0)
    assert report.trim.end_ms == pytest.approx(track.content_end_ms, abs=10.0)

    # one auto segment from the first sound, nothing else is filled in until milestone 2
    assert len(report.tempo_map) == 1
    segment = report.tempo_map[0]
    assert segment.source == "auto"
    assert segment.start_ms == report.trim.start_ms
    assert segment.confidence is None
    assert segment.bpm == pytest.approx(120.0, abs=1.0)
    assert report.beat_offset_ms is None
    assert report.meter_map == []
    assert report.sections == []
    assert report.edits == []


@pytest.mark.ffmpeg
def test_garbage_file_fails_at_decode(tmp_path):
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(bytes(range(256)) * 400)
    stages = []

    with pytest.raises(StageError) as err:
        run_analysis(junk, tmp_path, filename="junk.mp3", sha256="0" * 64, on_stage=stages.append)

    assert err.value.stage == "decode"
    assert err.value.message
    assert stages == ["decode"]


@pytest.mark.ffmpeg
def test_silent_wav_fails_at_trim(tmp_path):
    silent = tmp_path / "silent.wav"
    sf.write(silent, np.zeros(5 * 44100, dtype=np.float32), 44100, subtype="FLOAT")
    stages = []

    with pytest.raises(StageError) as err:
        run_analysis(silent, tmp_path, filename="silent.wav", sha256="0" * 64, on_stage=stages.append)

    assert err.value.stage == "trim"
    assert "silent" in err.value.message
    assert stages == ["decode", "trim"]


@pytest.mark.ffmpeg
def test_too_short_to_tempo_fails_at_tempo(tmp_path):
    # about half a second of clicks between the trim points, under the 3 s minimum
    src, _ = _copy_wav(tmp_path, ClickTrackSpec(beats=2, lead_silence_s=0.5, tail_silence_s=0.5))
    stages = []

    with pytest.raises(StageError) as err:
        run_analysis(src, tmp_path, filename="song.wav", sha256="0" * 64, on_stage=stages.append)

    assert err.value.stage == "tempo"
    assert stages == ["decode", "trim", "tempo"]
