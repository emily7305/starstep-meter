"""Measure madmom's timing bias on real songs, one csv row per file.

Usage: python scripts/measure_bias_local.py <folder> [--out measure_bias.csv] [--window-ms 30]
       [--threshold-db -60] [--recursive]

Takes madmom's raw beats (no bias shift, no snap, no octave check) and finds the strongest
onset within the window around each, using the same short-window spectral flux as the snap.
An offset is the raw beat minus that onset, so negative means madmom is early, the same sign
as MADMOM_BIAS_MS. Compare median_offset_ms with bias_ms, the -11.8 measured on click tracks.
The flux peak sits about 0.7 ms before a click's first sample, so on clicks a bias of exactly
-11.8 reads about -11.1 here. One song can be several ms off, look at the median over a folder.

Writes timing data only, never audio, and nothing next to the songs.
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

import numpy as np

# run from anywhere, the analysis package lives in the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.beats import MADMOM_BIAS_MS, madmom_available, madmom_import_error, track_beats  # noqa: E402
from backend.analysis.decode import decode_to_wav, load_mono  # noqa: E402
from backend.analysis.ffmpeg_tools import find_tool  # noqa: E402
from backend.analysis.ingest import ALLOWED_EXTENSIONS  # noqa: E402

# snap has no public function that gives the time of the strongest peak, only its strength
from backend.analysis.snap import MIN_STRENGTH, _window_peaks  # noqa: E402
from backend.analysis.trim import DEFAULT_THRESHOLD_DB, find_trim  # noqa: E402

COLUMNS = (
    "file", "duration_ms", "sample_rate", "beats", "beats_with_onset",
    "median_offset_ms", "mean_offset_ms", "p10_offset_ms", "p25_offset_ms", "p75_offset_ms", "p90_offset_ms",
    "iqr_ms", "mad_ms", "bias_ms", "median_minus_bias_ms", "error",
)
# wider than the snap's 20 ms, so a bias bigger on real songs than on clicks still lands inside
DEFAULT_WINDOW_MS = 30.0


def onset_offsets(
    samples: np.ndarray, sample_rate: int, beats_ms: np.ndarray, window_ms: float = DEFAULT_WINDOW_MS
) -> np.ndarray:
    """Raw beat minus its strongest onset within window_ms, in ms, for the beats that have one.

    Negative means the beat is early. A beat is left out when its window has no flux peak, or
    when the biggest one is under the snap's floor, 20% of the median over all beats.
    """
    if samples.ndim != 1:
        raise ValueError("onset_offsets expects mono samples")
    if window_ms <= 0:
        raise ValueError("window must be positive")

    beats = np.asarray(beats_ms, dtype=np.float64)
    found, biggest = _window_peaks(samples, sample_rate, beats, window_ms)
    with_peaks = biggest[biggest > 0]
    if len(with_peaks) == 0:
        return np.zeros(0)
    floor = MIN_STRENGTH * float(np.median(with_peaks))

    offsets = []
    for beat, entry, peak in zip(beats, found, biggest):
        if entry is None or peak < floor:
            continue
        strengths, peak_times = entry
        # the strongest peak, where the snap takes the nearest strong one, which in a full mix stays next to the raw beat
        onset_ms = peak_times[int(np.argmax(strengths))] / sample_rate * 1000.0
        offsets.append(beat - onset_ms)
    return np.array(offsets, dtype=np.float64)


def summarize(offsets: np.ndarray) -> dict[str, float]:
    if len(offsets) == 0:
        raise ValueError("no offsets to summarize")
    p10, p25, median, p75, p90 = np.percentile(offsets, [10, 25, 50, 75, 90])
    return {
        "median_offset_ms": float(median),
        "mean_offset_ms": float(offsets.mean()),
        "p10_offset_ms": float(p10),
        "p25_offset_ms": float(p25),
        "p75_offset_ms": float(p75),
        "p90_offset_ms": float(p90),
        "iqr_ms": float(p75 - p25),
        # plain, not scaled up to look like a standard deviation
        "mad_ms": float(np.median(np.abs(offsets - median))),
    }


def _ms(value: float) -> str:
    # adding 0.0 turns a rounded -0.0 into 0.0, so the csv never says -0.000
    return f"{round(value, 3) + 0.0:.3f}"


def _find_songs(folder: Path, recursive: bool) -> list[tuple[str, Path]]:
    paths = folder.rglob("*") if recursive else folder.iterdir()
    songs = [(p.relative_to(folder).as_posix(), p) for p in paths if p.suffix.lower() in ALLOWED_EXTENSIONS and p.is_file()]
    # names are unique, so the sort never has to compare paths
    return sorted(songs)


def _row(name: str, duration_ms: float, sample_rate: int, beats: int, offsets: np.ndarray) -> dict[str, str]:
    stats = summarize(offsets)
    row = dict.fromkeys(COLUMNS, "")
    row.update({column: _ms(value) for column, value in stats.items()})
    row.update(
        file=name,
        duration_ms=_ms(duration_ms),
        sample_rate=str(sample_rate),
        beats=str(beats),
        beats_with_onset=str(len(offsets)),
        bias_ms=_ms(MADMOM_BIAS_MS),
        # where a beat shifted by the bias would sit against the onsets, positive is late
        median_minus_bias_ms=_ms(stats["median_offset_ms"] - MADMOM_BIAS_MS),
    )
    return row


def _scrub(message: str, folder: Path) -> str:
    # the csv gets pasted elsewhere, so no absolute paths or user names in it
    for path, stand_in in ((folder.resolve(), "<folder>"), (Path(tempfile.gettempdir()).resolve(), "<tmp>"), (Path.home(), "~")):
        for spelling in {str(path), path.as_posix()}:
            message = message.replace(spelling, stand_in)
    return message


def _error_row(name: str, message: str) -> dict[str, str]:
    row = dict.fromkeys(COLUMNS, "")
    # one line, so the progress output and the pasted csv stay readable
    row.update(file=name, error=" ".join(message.split()))
    return row


def _measure(name: str, path: Path, folder: Path, window_ms: float, threshold_db: float) -> dict[str, str]:
    stage = "decode"
    try:
        # the decoded wav only ever exists in here
        with tempfile.TemporaryDirectory(prefix="starstep-bias-", ignore_cleanup_errors=True) as tmp:
            decoded = decode_to_wav(path, Path(tmp) / "decoded.wav")
            samples, sample_rate = load_mono(decoded.path)
        stage = "trim"
        trim = find_trim(samples, sample_rate, threshold_db=threshold_db)
        stage = "beats"
        tracked = track_beats(samples, sample_rate, trim.start_ms, trim.end_ms, tracker="madmom")
        stage = "onsets"
        offsets = onset_offsets(samples, sample_rate, tracked.times_ms, window_ms)
        if len(offsets) == 0:
            raise ValueError(f"none of the {len(tracked.times_ms)} beats has an onset within {window_ms:g} ms")
        return _row(name, decoded.duration_ms, sample_rate, len(tracked.times_ms), offsets)
    except Exception as exc:
        # one bad file shouldn't cost the rest of the folder
        return _error_row(name, _scrub(f"failed at {stage}: {str(exc) or type(exc).__name__}", folder))


def _progress_text(row: dict[str, str]) -> str:
    if row["error"]:
        return row["error"]
    return f"ok, median {row['median_offset_ms']} ms over {row['beats_with_onset']} of {row['beats']} beats"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, default=Path("measure_bias.csv"), help="csv to write, in the current directory by default")
    parser.add_argument("--window-ms", type=float, default=DEFAULT_WINDOW_MS, help="look for the onset this far either side of each beat")
    parser.add_argument("--threshold-db", type=float, default=DEFAULT_THRESHOLD_DB, help="trim threshold, relative to the loudest frame")
    parser.add_argument("--recursive", action="store_true", help="also look in subfolders")
    args = parser.parse_args(argv)
    # written so that nan fails too
    if not 0 < args.window_ms < float("inf"):
        parser.error("--window-ms must be positive")
    if not args.threshold_db < 0:
        parser.error("--threshold-db must be below 0")

    folder: Path = args.folder
    if not folder.is_dir():
        print(f"no such folder: {folder}", file=sys.stderr)
        return 2
    songs = _find_songs(folder, args.recursive)
    if not songs:
        hint = "" if args.recursive else ", add --recursive to look in subfolders"
        print(f"no audio files in {folder} (expected {' '.join(ALLOWED_EXTENSIONS)}){hint}", file=sys.stderr)
        return 2
    for tool in ("ffmpeg", "ffprobe"):
        if find_tool(tool) is None:
            print(f"{tool} not found on PATH, install it first", file=sys.stderr)
            return 2
    # the bias is madmom's, a run on the librosa fallback would measure something else
    if not madmom_available():
        print("madmom is not installed, install it with pip install -e .[madmom]", file=sys.stderr)
        return 2
    error = madmom_import_error()
    if error is not None:
        print(f"madmom is installed but doesn't import ({' '.join(error.split())})", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    medians: list[float] = []
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for i, (name, path) in enumerate(songs, start=1):
            row = _measure(name, path, folder, args.window_ms, args.threshold_db)
            writer.writerow([row[column] for column in COLUMNS])
            if row["error"]:
                failed += 1
            else:
                medians.append(float(row["median_offset_ms"]))
            print(f"[{i}/{len(songs)}] {name}  {_progress_text(row)}", file=sys.stderr)
    if medians:
        summary = f"folder median {_ms(float(np.median(medians)))} ms (bias {_ms(MADMOM_BIAS_MS)} ms)"
    else:
        summary = "no song gave a median"
    print(f"wrote {args.out} ({len(songs)} files, {failed} failed), {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
