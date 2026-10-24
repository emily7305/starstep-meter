import csv
import importlib.util
import shutil
import tempfile
from pathlib import Path

import pytest

from tests.synth import ClickTrackSpec, cached_click_wav

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_local.py"

# spelled out here so a reordered column in the script fails a test
HEADER = [
    "file", "duration_ms", "codec", "sample_rate", "tracker", "octave",
    "segments", "segment_starts_ms", "segment_bpms", "segment_confidences",
    "residual_rms_ms", "residual_p95_ms", "residual_max_ms", "outliers", "confidence",
    "beats", "beats_snapped", "beats_not_snapped", "median_snap_move_ms", "error",
]


def _load_script():
    # scripts/ isn't a package
    spec = importlib.util.spec_from_file_location("eval_local", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


eval_local = _load_script()


def _put_click(folder: Path, name: str, bpm: float = 120.0) -> Path:
    # a copy, the cached fixture stays where the other tests expect it
    cached, _ = cached_click_wav(ClickTrackSpec(bpm=bpm, accent_downbeats=True))
    dest = folder / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, dest)
    return dest


def _run(folder: Path, out: Path, *extra: str) -> int:
    return eval_local.main([str(folder), "--out", str(out), "--tracker", "librosa", *extra])


def _read(out: Path) -> tuple[list[str], list[dict[str, str]]]:
    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], [dict(zip(rows[0], row)) for row in rows[1:]]


@pytest.mark.ffmpeg
def test_two_songs_give_two_rows_and_the_txt_is_ignored(capsys, tmp_path):
    songs = tmp_path / "songs"
    _put_click(songs, "slow.wav", bpm=120)
    _put_click(songs, "fast.wav", bpm=150)
    (songs / "notes.txt").write_text("not audio\n", encoding="utf-8")
    out = tmp_path / "eval.csv"

    code = _run(songs, out)

    captured = capsys.readouterr()
    assert code == 0
    header, rows = _read(out)
    assert header == HEADER
    # sorted by relative path
    assert [row["file"] for row in rows] == ["fast.wav", "slow.wav"]
    for row, bpm in zip(rows, (150.0, 120.0)):
        assert row["segments"] == "1"
        assert float(row["segment_bpms"]) == pytest.approx(bpm, abs=0.01)
        assert int(row["beats_snapped"]) + int(row["beats_not_snapped"]) == int(row["beats"])
        assert row["error"] == ""
    # progress and the summary line go to stderr
    assert captured.out == ""
    assert "[1/2] fast.wav  ok, 1 segment, " in captured.err
    assert captured.err.strip().splitlines()[-1] == f"wrote {out} (2 files, 0 failed)"


@pytest.mark.ffmpeg
def test_a_broken_file_becomes_an_error_row_and_the_rest_still_run(capsys, tmp_path):
    songs = tmp_path / "songs"
    _put_click(songs, "good.wav")
    (songs / "junk.mp3").write_bytes(bytes(range(256)) * 400)
    out = tmp_path / "eval.csv"

    code = _run(songs, out)

    captured = capsys.readouterr()
    assert code == 0
    _, rows = _read(out)
    by_file = {row["file"]: row for row in rows}
    assert set(by_file) == {"good.wav", "junk.mp3"}
    junk = by_file["junk.mp3"]
    assert junk["error"].startswith("failed at decode")
    assert all(value == "" for column, value in junk.items() if column not in ("file", "error"))
    good = by_file["good.wav"]
    assert good["error"] == ""
    assert good["duration_ms"] != ""
    assert good["segment_bpms"] != ""
    assert "junk.mp3  failed at decode" in captured.err
    assert captured.err.strip().splitlines()[-1] == f"wrote {out} (2 files, 1 failed)"


@pytest.mark.ffmpeg
def test_recursive_finds_subfolders_with_posix_names(tmp_path):
    songs = tmp_path / "songs"
    _put_click(songs, "sub/song.wav")
    out = tmp_path / "eval.csv"

    # top level only, nothing there
    assert _run(songs, out) == 2
    assert not out.exists()

    assert _run(songs, out, "--recursive") == 0
    _, rows = _read(out)
    assert [row["file"] for row in rows] == ["sub/song.wav"]
    assert rows[0]["error"] == ""


def test_missing_and_empty_folders_exit_2_without_a_csv(capsys, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("not audio\n", encoding="utf-8")
    out = tmp_path / "out" / "eval.csv"

    assert _run(tmp_path / "nope", out) == 2
    assert "no such folder" in capsys.readouterr().err
    assert _run(empty, out) == 2
    captured = capsys.readouterr()
    assert "no audio files" in captured.err
    assert captured.out == ""
    # not even the parent folder
    assert not out.parent.exists()


@pytest.mark.ffmpeg
def test_only_the_csv_is_written_and_the_decoded_wav_is_deleted(monkeypatch, tmp_path):
    songs = tmp_path / "songs"
    _put_click(songs, "song.wav")
    out = tmp_path / "out" / "eval.csv"
    # temp dirs land under tmp_path for this run, so anything left behind shows up in the snapshot
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    seen = []
    real = eval_local.run_analysis

    def spy(path, work_dir, **kwargs):
        result = real(path, work_dir, **kwargs)
        seen.append((work_dir, (work_dir / "decoded.wav").exists()))
        return result

    monkeypatch.setattr(eval_local, "run_analysis", spy)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    assert _run(songs, out) == 0

    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after - before == {out}
    assert before - after == set()
    # the wav did exist while the file ran, and its folder is gone now
    (work_dir, had_wav), = seen
    assert work_dir.parent == scratch
    assert had_wav
    assert not work_dir.exists()


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_missing_tool_exits_2(monkeypatch, capsys, tmp_path, missing):
    songs = tmp_path / "songs"
    songs.mkdir()
    # never decoded, the tool check comes first
    (songs / "song.wav").write_bytes(b"x")
    out = tmp_path / "eval.csv"
    monkeypatch.setattr(eval_local, "find_tool", lambda name: None if name == missing else f"/usr/bin/{name}")

    code = _run(songs, out)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert f"{missing} not found on PATH, install it first" in captured.err
    assert not out.exists()


def test_bad_bpm_range_is_a_usage_error(capsys, tmp_path):
    with pytest.raises(SystemExit) as err:
        eval_local.main([str(tmp_path), "--min-bpm", "200", "--max-bpm", "100"])

    assert err.value.code == 2
    assert "min_bpm < max_bpm" in capsys.readouterr().err


def test_error_text_has_no_absolute_paths(tmp_path):
    folder = tmp_path / "my songs"
    message = f"failed: can't read {folder / 'a.mp3'} or {Path.home() / 'x'}"

    scrubbed = eval_local._scrub(message, folder)

    assert str(tmp_path) not in scrubbed
    assert str(Path.home()) not in scrubbed
    assert "<folder>" in scrubbed
