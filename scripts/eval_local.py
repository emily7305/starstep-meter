"""Run the analysis on every song in a folder and write one csv row per file.

Usage: python scripts/eval_local.py <folder> [--out eval_local.csv] [--tracker auto|madmom|librosa]
       [--min-bpm 60] [--max-bpm 320] [--cross-check-ms 20] [--recursive]

Writes timing data only, never audio, and nothing next to the songs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import tempfile
from pathlib import Path

import numpy as np

# run from anywhere, the analysis package lives in the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ffmpeg_tools import find_tool  # noqa: E402
from backend.analysis.ingest import ALLOWED_EXTENSIONS  # noqa: E402
from backend.analysis.cross_check import CrossCheckConfig  # noqa: E402
from backend.analysis.octave import summary  # noqa: E402
from backend.analysis.pipeline import AnalysisConfig, AnalysisOutput, StageError, run_analysis, snap_shift_ms  # noqa: E402
from backend.analysis.tempo_range import DEFAULT_MAX_BPM, DEFAULT_MIN_BPM, TempoRange  # noqa: E402

COLUMNS = (
    "file", "duration_ms", "codec", "sample_rate", "tracker", "octave",
    "segments", "segment_starts_ms", "segment_bpms", "segment_confidences",
    "residual_rms_ms", "residual_p95_ms", "residual_max_ms", "outliers", "confidence",
    "ratio_merged", "offbeat_runs", "meter", "notation_suggestions", "cross_check_ms", "low_confidence",
    "beats", "beats_snapped", "beats_not_snapped", "median_snap_move_ms", "error",
)
_CHUNK = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _find_songs(folder: Path, recursive: bool) -> list[tuple[str, Path]]:
    paths = folder.rglob("*") if recursive else folder.iterdir()
    songs = [(p.relative_to(folder).as_posix(), p) for p in paths if p.suffix.lower() in ALLOWED_EXTENSIONS and p.is_file()]
    # names are unique, so the sort never has to compare paths
    return sorted(songs)


def _cross_check(out: AnalysisOutput) -> str:
    # per segment, - with too few beats to compare, ! when flagged. empty without a cross-check
    if out.cross_check is None:
        return ""
    return " ".join(
        "-" if c.disagreement_ms is None else f"{c.disagreement_ms:.2f}{'!' if c.flagged else ''}" for c in out.cross_check.segments
    )


def _row(name: str, out: AnalysisOutput) -> dict[str, str]:
    tempo = out.tempo
    residuals = np.abs(tempo.residuals_ms)
    beats = len(out.snap.snapped)
    snapped = int(out.snap.snapped.sum())
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        file=name,
        duration_ms=f"{out.decoded.duration_ms:.3f}",
        codec=out.decoded.codec,
        sample_rate=str(out.decoded.sample_rate),
        tracker=out.tracked.tracker,
        octave=summary(out.octave),
        segments=str(len(tempo.segments)),
        segment_starts_ms=" ".join(f"{s.start_ms:.3f}" for s in tempo.segments),
        segment_bpms=" ".join(f"{s.fit.bpm:.4f}" for s in tempo.segments),
        segment_confidences=" ".join(f"{c:.3f}" for c in out.confidence.segments),
        residual_rms_ms=f"{tempo.residual_rms_ms:.3f}",
        residual_p95_ms=f"{np.percentile(residuals, 95):.3f}",
        residual_max_ms=f"{residuals.max():.3f}",
        outliers=str(int((~tempo.inliers).sum())),
        confidence=f"{tempo.confidence:.3f}",
        ratio_merged=" ".join(f"{m.ratio}:{m.start_ms:.0f}-{m.end_ms:.0f}" for s in tempo.segments for m in s.ratio_merges),
        offbeat_runs=" ".join(f"{r.start_ms:.0f}-{r.end_ms:.0f}" for s in tempo.segments for r in s.offbeat_runs),
        meter=" ".join(f"{r.numerator}/{r.denominator}:{r.start_ms:.0f}" for r in out.meter.runs),
        notation_suggestions=" ".join(f"{s.kind}:{s.start_ms:.0f}-{s.end_ms:.0f}:{s.score:.2f}" for s in out.report.notation_suggestions),
        cross_check_ms=_cross_check(out),
        low_confidence=" ".join(f"{s.start_ms:.0f}-{s.end_ms:.0f}:{s.confidence:.2f}" for s in out.confidence.spans if s.low),
        beats=str(beats),
        beats_snapped=str(snapped),
        beats_not_snapped=str(beats - snapped),
        median_snap_move_ms=f"{snap_shift_ms(out.tracked, out.snap):.3f}",
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


def _analyze(name: str, path: Path, folder: Path, config: AnalysisConfig) -> dict[str, str]:
    try:
        sha256 = _sha256(path)
        # the decoded wav only ever exists in here
        with tempfile.TemporaryDirectory(prefix="starstep-eval-", ignore_cleanup_errors=True) as tmp:
            out = run_analysis(path, Path(tmp), filename=name, sha256=sha256, config=config)
        return _row(name, out)
    except StageError as exc:
        return _error_row(name, _scrub(f"failed at {exc.stage}: {exc.message}", folder))
    except Exception as exc:
        # one bad file shouldn't cost the rest of the folder
        return _error_row(name, _scrub(f"failed: {str(exc) or type(exc).__name__}", folder))


def _progress_text(row: dict[str, str]) -> str:
    if row["error"]:
        return row["error"]
    count = int(row["segments"])
    first_bpm = row["segment_bpms"].split()[0]
    return f"ok, {count} segment{'' if count == 1 else 's'}, {first_bpm} bpm"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--out", type=Path, default=Path("eval_local.csv"), help="csv to write, in the current directory by default")
    parser.add_argument("--tracker", choices=["auto", "madmom", "librosa"], default="auto", help="auto uses madmom when it's installed")
    parser.add_argument("--min-bpm", type=float, default=DEFAULT_MIN_BPM, help="slowest tempo any tempo path considers")
    parser.add_argument("--max-bpm", type=float, default=DEFAULT_MAX_BPM, help="fastest tempo any tempo path considers")
    parser.add_argument(
        "--cross-check-ms",
        type=float,
        default=CrossCheckConfig().max_disagreement_ms,
        help="flag a tempo segment where madmom and librosa are further apart than this",
    )
    parser.add_argument("--recursive", action="store_true", help="also look in subfolders")
    args = parser.parse_args(argv)
    try:
        config = AnalysisConfig(
            tracker=args.tracker,
            tempo_range=TempoRange(args.min_bpm, args.max_bpm),
            cross_check=CrossCheckConfig(args.cross_check_ms),
        )
    except ValueError as exc:
        parser.error(str(exc))

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

    args.out.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for i, (name, path) in enumerate(songs, start=1):
            row = _analyze(name, path, folder, config)
            writer.writerow([row[column] for column in COLUMNS])
            failed += bool(row["error"])
            print(f"[{i}/{len(songs)}] {name}  {_progress_text(row)}", file=sys.stderr)
    print(f"wrote {args.out} ({len(songs)} files, {failed} failed)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
