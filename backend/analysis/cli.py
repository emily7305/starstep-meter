"""Analyze one file without the server.

Usage: python -m backend.analysis.cli <file> [--threshold-db -60] [--snap-window-ms 20]
       [--tracker auto|madmom|librosa] [--beats beats.json] [--work-dir DIR] [-v]

Prints the timing report JSON to stdout. Stage progress and debug
numbers go to stderr with -v, so stdout stays pipeable. --beats also
writes the beats file.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from backend.analysis.ffmpeg_tools import ToolNotFoundError
from backend.analysis.ingest import DEFAULT_MAX_BYTES, IngestError, ingest_file
from backend.analysis.pipeline import AnalysisConfig, StageError, run_analysis, snap_shift_ms
from backend.analysis.snap import DEFAULT_WINDOW_MS
from backend.analysis.trim import DEFAULT_THRESHOLD_DB


def _analyze(src: Path, work_dir: Path, args: argparse.Namespace) -> int:
    def log(msg: str) -> None:
        if args.verbose:
            print(msg, file=sys.stderr)

    try:
        ingested = ingest_file(src, work_dir, max_bytes=args.max_mb * 1024 * 1024)
    except (IngestError, ToolNotFoundError) as exc:
        print(f"can't analyze {src.name}: {exc}", file=sys.stderr)
        return 2
    log(f"ingest  {ingested.probe.format_name} / {ingested.probe.codec_name}, {ingested.size_bytes} bytes")

    try:
        out = run_analysis(
            ingested.original_path,
            work_dir,
            filename=src.name,
            sha256=ingested.sha256,
            on_stage=lambda stage: log(f"stage   {stage}"),
            config=AnalysisConfig(trim_threshold_db=args.threshold_db, snap_window_ms=args.snap_window_ms, tracker=args.tracker),
        )
    except StageError as exc:
        print(f"analysis failed at {exc.stage}: {exc.message}", file=sys.stderr)
        return 1

    fit = out.fit
    log(f"decode  {out.decoded.sample_rate} hz, {out.decoded.num_samples} samples, {out.decoded.codec}, decoder padding {out.decoded.decoder_padding_samples} samples")
    log(f"trim    {out.trim.start_ms:.1f} -> {out.trim.end_ms:.1f} ms at {out.trim.threshold_db:g} db")
    log(f"beats   {out.tracked.tracker}, {len(out.tracked.times_ms)} beats")
    log(f"snap    {int(out.snap.snapped.sum())} of {len(out.snap.snapped)} snapped within {out.snap.window_ms:g} ms, median move {snap_shift_ms(out.tracked, out.snap):+.2f} ms")
    log(
        f"tempo   {fit.bpm:.4f} bpm, first downbeat {fit.offset_ms:.3f} ms, residual rms {fit.residual_rms_ms:.2f} ms, "
        f"{int((~fit.inliers).sum())} outliers, confidence {fit.confidence:.3f}"
    )
    if args.beats is not None:
        args.beats.write_text(out.beats.model_dump_json(indent=2) + "\n", encoding="utf-8")
        log(f"wrote   {args.beats}")
    print(out.report.model_dump_json(indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.analysis.cli", description="print the timing report for one audio file")
    parser.add_argument("file", type=Path)
    parser.add_argument("--threshold-db", type=float, default=DEFAULT_THRESHOLD_DB, help="trim threshold relative to the loudest frame")
    parser.add_argument("--snap-window-ms", type=float, default=DEFAULT_WINDOW_MS, help="how far a beat may move onto an onset")
    parser.add_argument("--tracker", choices=["auto", "madmom", "librosa"], default="auto", help="auto uses madmom when it's installed")
    parser.add_argument("--beats", type=Path, help="also write the beats file here")
    parser.add_argument("--max-mb", type=int, default=DEFAULT_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--work-dir", type=Path, help="keep the copied original and decoded wav here instead of a temp dir")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    src: Path = args.file
    if not src.is_file():
        print(f"no such file: {src}", file=sys.stderr)
        return 2

    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        return _analyze(src, args.work_dir, args)
    # ignore_cleanup_errors because windows sometimes still holds the wav for a moment
    with tempfile.TemporaryDirectory(prefix="starstep-", ignore_cleanup_errors=True) as tmp:
        return _analyze(src, Path(tmp), args)


if __name__ == "__main__":
    sys.exit(main())
