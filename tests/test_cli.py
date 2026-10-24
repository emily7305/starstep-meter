import json

import numpy as np
import pytest
import soundfile as sf

from backend.analysis.cli import main
from backend.schema.models import TimingReport
from tests.synth import ClickTrackSpec, cached_click_wav


@pytest.mark.ffmpeg
def test_cli_prints_a_valid_report(capsys):
    wav, track = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0))

    code = main([str(wav)])

    out = capsys.readouterr().out
    assert code == 0
    # json.loads first so a stray log line on stdout fails as bad json, not as a pydantic error
    report = TimingReport.model_validate(json.loads(out))
    assert report.trim.start_ms == pytest.approx(2000.0, abs=10.0)
    assert report.trim.start_ms == pytest.approx(track.content_start_ms, abs=10.0)
    assert report.tempo_map[0].bpm == pytest.approx(120.0, abs=1.0)
    assert report.source.filename == wav.name


@pytest.mark.ffmpeg
def test_cli_verbose_logs_to_stderr_and_keeps_work_dir(capsys, tmp_path):
    wav, _ = cached_click_wav(ClickTrackSpec(bpm=120, lead_silence_s=2.0))
    work = tmp_path / "keep"

    code = main([str(wav), "-v", "--work-dir", str(work)])

    captured = capsys.readouterr()
    assert code == 0
    # stdout has to stay pipeable with -v on
    TimingReport.model_validate(json.loads(captured.out))
    for stage in ("decode", "trim", "tempo"):
        assert stage in captured.err
    assert (work / "original.wav").exists()
    assert (work / "decoded.wav").exists()


def test_cli_rejects_a_txt_file(capsys, tmp_path):
    # fails on the extension, ffprobe never gets involved
    notes = tmp_path / "notes.txt"
    notes.write_text("not audio\n", encoding="utf-8")

    code = main([str(notes)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "unsupported file type" in captured.err


def test_cli_missing_file_is_a_usage_error(capsys, tmp_path):
    code = main([str(tmp_path / "nope.wav")])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "no such file" in captured.err


@pytest.mark.ffmpeg
def test_cli_text_file_renamed_mp3_is_rejected(capsys, tmp_path):
    fake = tmp_path / "fake.mp3"
    fake.write_text("grocery list, not a song\n" * 200, encoding="utf-8")

    code = main([str(fake)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "not a readable audio file" in captured.err


@pytest.mark.ffmpeg
def test_cli_silent_wav_exits_1_with_the_stage(capsys, tmp_path):
    # 1 is "analysis failed", 2 is "never started", scripts care about the difference
    silent = tmp_path / "silent.wav"
    sf.write(silent, np.zeros(5 * 44100, dtype=np.float32), 44100, subtype="FLOAT")

    code = main([str(silent)])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "failed at trim" in captured.err
