import csv
import importlib.util
import re
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.analysis.beats import MADMOM_BIAS_MS, TrackedBeats
from backend.analysis.decode import DecodedAudio
from tests.synth import ClickTrackSpec, _click, click_track, write_wav

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_bias_local.py"

# spelled out here so a reordered column in the script fails a test
HEADER = [
    "file", "duration_ms", "sample_rate", "beats", "beats_with_onset",
    "median_offset_ms", "mean_offset_ms", "p10_offset_ms", "p25_offset_ms", "p75_offset_ms", "p90_offset_ms",
    "iqr_ms", "mad_ms", "bias_ms", "median_minus_bias_ms", "error",
]


def _load_script():
    # scripts/ isn't a package
    spec = importlib.util.spec_from_file_location("measure_bias_local", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure = _load_script()

# the flux peak sits about 0.7 ms before a click's first sample (see docs/decisions.md, snapped beats
# land -0.71 to -0.77 ms from the onsets), so beats put 12 ms before a click read about -11.3
EARLY_MS = 12.0
EXPECTED_MS = -11.3
TOLERANCE_MS = 0.3

SR = 44100
CLICK = ClickTrackSpec()

CASES = [
    pytest.param(ClickTrackSpec(), id="44k"),
    pytest.param(ClickTrackSpec(sample_rate=48000), id="48k"),
    pytest.param(ClickTrackSpec(noise_floor_db=-90.0), id="44k-noise90"),
]


# --- onset_offsets ---


@pytest.mark.parametrize("spec", CASES)
def test_beats_12_ms_before_every_click_read_about_minus_11_3(spec):
    track = click_track(spec)

    offsets = measure.onset_offsets(track.samples, track.sample_rate, track.onsets_ms - EARLY_MS, window_ms=30.0)

    assert len(offsets) == len(track.onsets_ms)
    assert np.median(offsets) == pytest.approx(EXPECTED_MS, abs=TOLERANCE_MS)
    # the plain check, within 1.5 ms of the 12 ms the beats were moved
    assert abs(np.median(offsets) - -EARLY_MS) <= 1.5


def _clicks(clicks_ms_amplitude):
    shape = _click(SR, CLICK.click_freq_hz, CLICK.click_ms, CLICK.click_decay_ms)
    audio = np.zeros(4 * SR)
    for ms, amplitude in clicks_ms_amplitude:
        start = int(round(ms / 1000.0 * SR))
        audio[start:start + len(shape)] += shape * amplitude
    return audio.astype(np.float32)


@pytest.mark.parametrize("weak, kept", [(0.1, 4), (0.5, 5)], ids=["weak-click-10pct", "click-50pct"])
def test_a_beat_with_no_onset_or_a_weak_one_is_left_out(weak, kept):
    full = CLICK.amplitude
    clicks = [(400.0, full), (800.0, full), (1200.0, full * weak), (1600.0, full), (2000.0, full)]
    audio = _clicks(clicks)
    # the last beat sits in silence, nothing there to measure
    beats = np.array([ms - EARLY_MS for ms, _ in clicks] + [3000.0])

    offsets = measure.onset_offsets(audio, SR, beats, window_ms=30.0)

    # the floor is 20% of the median biggest peak, flux is linear in amplitude
    assert len(offsets) == kept
    assert np.median(offsets) == pytest.approx(EXPECTED_MS, abs=TOLERANCE_MS)


def test_the_window_decides_whether_a_click_is_found():
    track = click_track(ClickTrackSpec())
    early = track.onsets_ms - 40.0

    narrow = measure.onset_offsets(track.samples, track.sample_rate, early, window_ms=30.0)
    wide = measure.onset_offsets(track.samples, track.sample_rate, early, window_ms=50.0)

    assert len(narrow) == 0
    assert len(wide) == len(early)
    assert np.median(wide) == pytest.approx(-39.3, abs=TOLERANCE_MS)


def test_onset_offsets_with_no_beats_is_empty():
    track = click_track(ClickTrackSpec())

    offsets = measure.onset_offsets(track.samples, track.sample_rate, np.zeros(0), window_ms=30.0)

    assert offsets.shape == (0,)


def test_onset_offsets_refuses_stereo_and_a_window_that_is_not_positive():
    with pytest.raises(ValueError, match="mono"):
        measure.onset_offsets(np.zeros((2, SR), dtype=np.float32), SR, np.array([500.0]), window_ms=30.0)
    for window_ms in (0.0, -5.0):
        with pytest.raises(ValueError, match="positive"):
            measure.onset_offsets(np.zeros(SR, dtype=np.float32), SR, np.array([500.0]), window_ms=window_ms)


# --- summarize ---


def test_summarize_on_a_hand_made_array():
    stats = measure.summarize(np.array([-20.0, -15.0, -12.0, -10.0, -8.0]))

    # percentiles interpolate between neighbours: p10 is 0.4 of the way from -20 to -15, p90 is 0.6 from -10 to -8
    # distances from the median -12 are 8, 3, 0, 2, 4 so their median is 3
    assert stats == pytest.approx({
        "median_offset_ms": -12.0,
        "mean_offset_ms": -13.0,
        "p10_offset_ms": -18.0,
        "p25_offset_ms": -15.0,
        "p75_offset_ms": -10.0,
        "p90_offset_ms": -8.8,
        "iqr_ms": 5.0,
        "mad_ms": 3.0,
    })


def test_summarize_refuses_nothing_to_summarize():
    with pytest.raises(ValueError, match="no offsets"):
        measure.summarize(np.zeros(0))


def test_a_value_that_rounds_to_zero_has_no_minus_sign():
    assert measure._ms(-0.0004) == "0.000"
    assert measure._ms(-11.8) == "-11.800"
    assert measure._ms(0.51894) == "0.519"


def test_error_text_has_no_absolute_paths(tmp_path):
    folder = tmp_path / "my songs"
    message = f"failed: can't read {folder / 'a.mp3'} or {Path.home() / 'x'}"

    scrubbed = measure._scrub(message, folder)

    assert str(tmp_path) not in scrubbed
    assert str(Path.home()) not in scrubbed
    assert "<folder>" in scrubbed


# --- the cli ---


def _read(out: Path) -> tuple[list[str], list[dict[str, str]]]:
    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return rows[0], [dict(zip(rows[0], row)) for row in rows[1:]]


def _run(folder: Path, out: Path, *extra: str) -> int:
    return measure.main([str(folder), "--out", str(out), *extra])


def _write_click(path: Path, spec: ClickTrackSpec) -> None:
    # generated into the test's own folder, never the repo's fixtures
    write_wav(click_track(spec), path)


def test_missing_and_empty_folders_exit_2_without_a_csv(capsys, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("not audio\n", encoding="utf-8")
    out = tmp_path / "out" / "bias.csv"

    assert _run(tmp_path / "nope", out) == 2
    assert "no such folder" in capsys.readouterr().err
    assert _run(empty, out) == 2
    captured = capsys.readouterr()
    assert "no audio files" in captured.err
    assert captured.out == ""
    # not even the parent folder
    assert not out.parent.exists()


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_missing_tool_exits_2(monkeypatch, capsys, tmp_path, missing):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "song.wav").write_bytes(b"x")
    out = tmp_path / "bias.csv"
    monkeypatch.setattr(measure, "find_tool", lambda name: None if name == missing else f"/usr/bin/{name}")

    code = _run(songs, out)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert f"{missing} not found on PATH, install it first" in captured.err
    assert not out.exists()


@pytest.mark.parametrize(
    "installed, import_error, message",
    [
        (False, None, "madmom is not installed"),
        (True, "AttributeError: module 'numpy' has no attribute 'float'\nsecond line", "madmom is installed but doesn't import (AttributeError"),
    ],
    ids=["missing", "broken"],
)
def test_no_madmom_is_one_line_and_nothing_runs(monkeypatch, capsys, tmp_path, installed, import_error, message):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "song.wav").write_bytes(b"x")
    out = tmp_path / "bias.csv"
    monkeypatch.setattr(measure, "find_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(measure, "madmom_available", lambda: installed)
    monkeypatch.setattr(measure, "madmom_import_error", lambda: import_error)

    def refuse(*args, **kwargs):
        raise AssertionError("a song was decoded")

    monkeypatch.setattr(measure, "decode_to_wav", refuse)

    code = _run(songs, out)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert message in captured.err
    assert not out.exists()


@pytest.mark.parametrize("flag, value, message", [
    ("--window-ms", "0", "--window-ms must be positive"),
    ("--window-ms", "-3", "--window-ms must be positive"),
    ("--window-ms", "nan", "--window-ms must be positive"),
    ("--threshold-db", "0", "--threshold-db must be below 0"),
    ("--threshold-db", "12", "--threshold-db must be below 0"),
])
def test_bad_options_are_usage_errors(capsys, tmp_path, flag, value, message):
    with pytest.raises(SystemExit) as err:
        measure.main([str(tmp_path), flag, value])

    assert err.value.code == 2
    assert message in capsys.readouterr().err


# with ffmpeg and madmom swapped for stand-ins, so the csv and the folder handling are checked everywhere


@pytest.fixture
def stand_ins(monkeypatch):
    spec = ClickTrackSpec(bpm=120, accent_downbeats=True)
    onsets = click_track(spec).onsets_ms
    seen = {"work_dirs": [], "trackers": []}

    def fake_decode(src, dst):
        shutil.copyfile(src, dst)
        seen["work_dirs"].append(dst.parent)
        # a junk file fails here, the way ffmpeg refuses it
        info = sf.info(str(dst))
        return DecodedAudio(
            path=dst,
            sample_rate=info.samplerate,
            num_samples=info.frames,
            duration_ms=info.frames / info.samplerate * 1000.0,
            codec="pcm_f32le",
            decoder_padding_samples=0,
        )

    def fake_track(samples, sample_rate, start_ms, end_ms, tracker="auto", **kwargs):
        seen["trackers"].append(tracker)
        return TrackedBeats(
            times_ms=onsets - EARLY_MS, positions=np.ones(len(onsets), dtype=np.int64), tracker="madmom", downbeats_known=True
        )

    monkeypatch.setattr(measure, "find_tool", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(measure, "madmom_available", lambda: True)
    monkeypatch.setattr(measure, "madmom_import_error", lambda: None)
    monkeypatch.setattr(measure, "decode_to_wav", fake_decode)
    monkeypatch.setattr(measure, "track_beats", fake_track)
    return spec, seen


def test_stand_in_run_writes_one_row_per_song_and_an_error_row_for_a_broken_one(capsys, monkeypatch, tmp_path, stand_ins):
    spec, seen = stand_ins
    songs = tmp_path / "songs"
    _write_click(songs / "click.wav", spec)
    _write_click(songs / "album" / "deep.wav", spec)
    (songs / "junk.mp3").write_bytes(bytes(range(256)) * 400)
    (songs / "notes.txt").write_text("not audio\n", encoding="utf-8")
    out = tmp_path / "out" / "bias.csv"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    code = _run(songs, out, "--recursive")

    captured = capsys.readouterr()
    assert code == 0
    header, rows = _read(out)
    assert header == HEADER
    # relative to the folder, posix separators, sorted
    assert [row["file"] for row in rows] == ["album/deep.wav", "click.wav", "junk.mp3"]
    by_file = {row["file"]: row for row in rows}

    good = by_file["click.wav"]
    assert good["error"] == ""
    assert good["sample_rate"] == "44100"
    assert good["beats"] == good["beats_with_onset"] == str(spec.beats)
    assert float(good["duration_ms"]) == pytest.approx(click_track(spec).duration_ms, abs=0.001)
    assert float(good["median_offset_ms"]) == pytest.approx(EXPECTED_MS, abs=TOLERANCE_MS)
    assert float(good["mad_ms"]) == pytest.approx(0.0, abs=0.01)
    assert float(good["bias_ms"]) == MADMOM_BIAS_MS
    assert float(good["median_minus_bias_ms"]) == pytest.approx(float(good["median_offset_ms"]) - MADMOM_BIAS_MS, abs=0.001)
    # three decimals everywhere there's a number
    for column in HEADER[1:-1]:
        assert re.fullmatch(r"-?\d+(\.\d{3})?", good[column]), (column, good[column])

    # a failing song has only its name and the error, and the rest still ran
    junk = by_file["junk.mp3"]
    assert junk["error"].startswith("failed at decode: ")
    assert "\n" not in junk["error"]
    assert str(tmp_path) not in junk["error"]
    assert all(value == "" for column, value in junk.items() if column not in ("file", "error"))

    # asked for madmom by name, "auto" could fall back to librosa and measure something else
    assert set(seen["trackers"]) == {"madmom"}
    assert captured.out == ""
    err_lines = captured.err.strip().splitlines()
    assert err_lines[0].startswith("[1/3] album/deep.wav  ok, median -11.")
    assert "junk.mp3  failed at decode" in captured.err
    assert err_lines[-1] == f"wrote {out} (3 files, 1 failed), folder median -11.281 ms (bias -11.800 ms)"

    # the csv is the only new file, and every decoded wav's folder is gone
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after - before == {out}
    assert before - after == set()
    assert len(seen["work_dirs"]) == 3
    for work_dir in seen["work_dirs"]:
        assert work_dir.parent == scratch
        assert not work_dir.exists()


def test_without_recursive_only_the_top_level_is_read(capsys, tmp_path, stand_ins):
    spec, _ = stand_ins
    songs = tmp_path / "songs"
    _write_click(songs / "album" / "deep.wav", spec)
    out = tmp_path / "bias.csv"

    assert _run(songs, out) == 2
    assert "add --recursive" in capsys.readouterr().err
    assert not out.exists()


def test_a_folder_where_every_song_fails_still_gets_its_rows_and_a_last_line(capsys, tmp_path, stand_ins):
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "junk.mp3").write_bytes(bytes(range(256)) * 400)
    out = tmp_path / "bias.csv"

    assert _run(songs, out) == 0

    _, rows = _read(out)
    assert len(rows) == 1 and rows[0]["error"] != ""
    assert capsys.readouterr().err.strip().splitlines()[-1] == f"wrote {out} (1 files, 1 failed), no song gave a median"


def test_a_song_where_no_beat_has_an_onset_is_an_error_row(capsys, tmp_path, stand_ins):
    spec, _ = stand_ins
    songs = tmp_path / "songs"
    _write_click(songs / "click.wav", spec)
    out = tmp_path / "bias.csv"

    # the stand-in beats sit 12 ms before the clicks, a 5 ms window can't reach them
    assert _run(songs, out, "--window-ms", "5") == 0

    _, rows = _read(out)
    assert rows[0]["error"].startswith("failed at onsets: none of the 40 beats has an onset within 5 ms")


# the real thing, ffmpeg decoding and madmom tracking a generated click track


@pytest.fixture(scope="module")
def madmom():
    return pytest.importorskip("madmom", reason="madmom not installed", exc_type=ImportError)


@pytest.mark.ffmpeg
@pytest.mark.usefixtures("madmom")
def test_end_to_end_on_a_click_track_with_a_broken_file_next_to_it(capsys, tmp_path):
    songs = tmp_path / "songs"
    spec = ClickTrackSpec(bpm=120, lead_silence_s=0.1375, accent_downbeats=True)
    _write_click(songs / "album" / "click.wav", spec)
    (songs / "album" / "junk.mp3").write_bytes(bytes(range(256)) * 400)
    out = tmp_path / "out" / "bias.csv"
    before = {p for p in tmp_path.rglob("*") if p.is_file()}

    code = _run(songs, out, "--recursive")

    captured = capsys.readouterr()
    assert code == 0
    header, rows = _read(out)
    assert header == HEADER
    by_file = {row["file"]: row for row in rows}
    # relative to the folder, not absolute
    assert set(by_file) == {"album/click.wav", "album/junk.mp3"}

    good = by_file["album/click.wav"]
    assert good["error"] == ""
    assert good["sample_rate"] == "44100"
    assert int(good["beats_with_onset"]) <= int(good["beats"])
    assert int(good["beats_with_onset"]) >= 30
    # early on clicks by 7 to 13 ms depending on where the 10 ms frames fall, so only the sign and rough size are checked
    assert -20.0 < float(good["median_offset_ms"]) < -5.0
    assert float(good["bias_ms"]) == MADMOM_BIAS_MS

    junk = by_file["album/junk.mp3"]
    assert junk["error"].startswith("failed at decode")
    assert all(value == "" for column, value in junk.items() if column not in ("file", "error"))
    assert captured.err.strip().splitlines()[-1].startswith(f"wrote {out} (2 files, 1 failed), folder median ")

    # no audio next to the songs or anywhere else, only the csv
    after = {p for p in tmp_path.rglob("*") if p.is_file()}
    assert after - before == {out}
    assert before - after == set()
