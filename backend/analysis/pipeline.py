"""Runs decode -> trim -> beats -> snap -> tempo and builds the report and beats file."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from backend.analysis.beats import FALLBACK_BEATS_PER_BAR, TrackedBeats, TrackerChoice, bar_numbers, track_beats
from backend.analysis.decode import DecodedAudio, decode_to_wav, load_mono
from backend.analysis.grid_fit import GridFit, fit_grid
from backend.analysis.snap import DEFAULT_WINDOW_MS, SnapResult, snap_to_onsets
from backend.analysis.trim import DEFAULT_THRESHOLD_DB, TrimResult, find_trim
from backend.schema.models import AudioSource, Beat, BeatsFile, TempoSegment, TimingReport, Trim

Stage = Literal["queued", "decode", "trim", "beats", "snap", "tempo", "done", "failed"]
STAGES: tuple[Stage, ...] = ("queued", "decode", "trim", "beats", "snap", "tempo", "done", "failed")
# the stages run_analysis actually runs, so the only ones a StageError can name
RunStage = Literal["decode", "trim", "beats", "snap", "tempo"]

DECODED_NAME = "decoded.wav"


class StageError(RuntimeError):
    def __init__(self, stage: RunStage, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class AnalysisConfig:
    trim_threshold_db: float = DEFAULT_THRESHOLD_DB
    snap_window_ms: float = DEFAULT_WINDOW_MS
    tracker: TrackerChoice = "auto"


@dataclass(frozen=True)
class AnalysisOutput:
    report: TimingReport
    beats: BeatsFile
    decoded: DecodedAudio
    trim: TrimResult
    tracked: TrackedBeats
    snap: SnapResult
    fit: GridFit


def _ms(value: float) -> float:
    # sub-microsecond digits are noise at 44.1 khz (one sample is ~0.023 ms), round so the json stays readable
    return round(float(value), 3)


def build_report(filename: str, sha256: str, decoded: DecodedAudio, trim: TrimResult, fit: GridFit) -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename=filename,
            sha256=sha256,
            duration_ms=_ms(decoded.duration_ms),
            sample_rate=decoded.sample_rate,
            codec=decoded.codec,
            decoder_padding_samples=decoded.decoder_padding_samples,
        ),
        trim=Trim(start_ms=_ms(trim.start_ms), end_ms=_ms(trim.end_ms)),
        beat_offset_ms=_ms(fit.offset_ms),
        # still from the first sound, the grid phase lives in beat_offset_ms only, see docs/decisions.md
        tempo_map=[
            TempoSegment(start_ms=_ms(trim.start_ms), bpm=round(fit.bpm, 4), confidence=round(fit.confidence, 3), source="auto")
        ],
    )


def build_beats_file(sha256: str, tracked: TrackedBeats, snap: SnapResult, fit: GridFit) -> BeatsFile:
    if tracked.downbeats_known:
        positions = tracked.positions
    else:
        # librosa's guess, counted on the fitted grid so a dropped beat doesn't slip the bar
        positions = fit.indices % FALLBACK_BEATS_PER_BAR + 1
    bars = bar_numbers(positions)
    beats = [
        Beat(
            # snap can land a fraction of a ms before 0 on audio that starts with a hit
            time_ms=max(0.0, _ms(snap.times_ms[i])),
            raw_time_ms=max(0.0, _ms(tracked.times_ms[i])),
            residual_ms=_ms(fit.residuals_ms[i]),
            bar=int(bars[i]),
            beat_in_bar=int(positions[i]),
            is_downbeat=bool(positions[i] == 1),
        )
        for i in range(len(tracked.times_ms))
    ]
    return BeatsFile(sha256=sha256, tracker=tracked.tracker, beats=beats)


def run_analysis(
    original_path: Path,
    work_dir: Path,
    filename: str,
    sha256: str,
    on_stage: Callable[[RunStage], None] | None = None,
    config: AnalysisConfig = AnalysisConfig(),
) -> AnalysisOutput:
    stage: RunStage = "decode"

    def enter(next_stage: RunStage) -> None:
        nonlocal stage
        stage = next_stage
        if on_stage is not None:
            on_stage(next_stage)

    try:
        enter("decode")
        decoded = decode_to_wav(original_path, work_dir / DECODED_NAME)
        samples, sample_rate = load_mono(decoded.path)

        enter("trim")
        trim = find_trim(samples, sample_rate, threshold_db=config.trim_threshold_db)

        enter("beats")
        tracked = track_beats(samples, sample_rate, trim.start_ms, trim.end_ms, tracker=config.tracker)

        enter("snap")
        snap = snap_to_onsets(samples, sample_rate, tracked.times_ms, window_ms=config.snap_window_ms)

        enter("tempo")
        fit = fit_grid(snap.times_ms, tracked.positions == 1, downbeats_known=tracked.downbeats_known)
    except Exception as exc:
        # keep whatever the stage said, the ui shows it as is
        raise StageError(stage, str(exc) or type(exc).__name__) from exc

    report = build_report(filename, sha256, decoded, trim, fit)
    beats = build_beats_file(sha256, tracked, snap, fit)
    return AnalysisOutput(report=report, beats=beats, decoded=decoded, trim=trim, tracked=tracked, snap=snap, fit=fit)


def snap_shift_ms(tracked: TrackedBeats, snap: SnapResult) -> float:
    # median move of the beats that did snap, for the cli's debug line
    moved = snap.times_ms[snap.snapped] - tracked.times_ms[snap.snapped]
    return float(np.median(moved)) if len(moved) else 0.0
