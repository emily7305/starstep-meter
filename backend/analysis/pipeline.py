"""Runs decode -> trim -> tempo and builds the timing report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.analysis.decode import DecodedAudio, decode_to_wav, load_mono
from backend.analysis.tempo import TempoResult, estimate_tempo
from backend.analysis.trim import DEFAULT_THRESHOLD_DB, TrimResult, find_trim
from backend.schema.models import AudioSource, TempoSegment, TimingReport, Trim

Stage = Literal["queued", "decode", "trim", "tempo", "done", "failed"]
STAGES: tuple[Stage, ...] = ("queued", "decode", "trim", "tempo", "done", "failed")
# the stages run_analysis actually runs, so the only ones a StageError can name
RunStage = Literal["decode", "trim", "tempo"]

DECODED_NAME = "decoded.wav"


class StageError(RuntimeError):
    def __init__(self, stage: RunStage, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class AnalysisConfig:
    trim_threshold_db: float = DEFAULT_THRESHOLD_DB


@dataclass(frozen=True)
class AnalysisOutput:
    report: TimingReport
    decoded: DecodedAudio
    trim: TrimResult
    tempo: TempoResult


def build_report(filename: str, sha256: str, decoded: DecodedAudio, trim: TrimResult, tempo: TempoResult) -> TimingReport:
    # sub-microsecond digits are noise at 44.1 khz (one sample is ~0.023 ms), round so the json stays readable
    return TimingReport(
        source=AudioSource(
            filename=filename,
            sha256=sha256,
            duration_ms=round(decoded.duration_ms, 3),
            sample_rate=decoded.sample_rate,
        ),
        trim=Trim(start_ms=round(trim.start_ms, 3), end_ms=round(trim.end_ms, 3)),
        beat_offset_ms=None,
        # one segment from the first sound, confidence stays null until beat regression in milestone 2
        tempo_map=[TempoSegment(start_ms=round(trim.start_ms, 3), bpm=round(tempo.bpm, 4), confidence=None, source="auto")],
    )


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

        enter("tempo")
        tempo = estimate_tempo(samples, sample_rate, trim.start_ms, trim.end_ms)
    except Exception as exc:
        # keep whatever the stage said, the ui shows it as is
        raise StageError(stage, str(exc) or type(exc).__name__) from exc

    report = build_report(filename, sha256, decoded, trim, tempo)
    return AnalysisOutput(report=report, decoded=decoded, trim=trim, tempo=tempo)
