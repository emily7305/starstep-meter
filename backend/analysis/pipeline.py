"""Runs decode -> trim -> beats -> snap -> tempo -> meter and builds the report and beats file."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from backend.analysis.beats import (
    FALLBACK_BEATS_PER_BAR,
    TrackedBeats,
    TrackerChoice,
    bar_numbers,
    bias_correction_ms,
    track_beats,
)
from backend.analysis.decode import DecodedAudio, decode_to_wav, load_mono
from backend.analysis.features import GridFeatures, band_flux, grid_features
from backend.analysis.meter import MeterConfig, MeterResult, infer_meter
from backend.analysis.meter_edit import keep_manual_meter
from backend.analysis.notation import (
    NotationConfig,
    Suggestion,
    feature_positions,
    feel_suggestions,
    fold_suggestions,
    from_fits,
)
from backend.analysis.notation_edit import keep_decided
from backend.analysis.octave import OctaveCheck, check_octave_per_segment, summary
from backend.analysis.snap import DEFAULT_WINDOW_MS, SnapResult, onset_strengths, snap_to_onsets
from backend.analysis.tempo_edit import keep_manual_segments
from backend.analysis.tempo_map import TempoMapConfig, TempoMapResult, build_tempo_map
from backend.analysis.tempo_range import TempoRange
from backend.analysis.trim import DEFAULT_THRESHOLD_DB, TrimResult, find_trim, stretch_level
from backend.schema.models import (
    AudioSource,
    Beat,
    BeatsFile,
    GridFeature,
    MeterSegment,
    NotationSuggestion,
    OffbeatRun,
    RatioMergedSection,
    TempoSegment,
    TimingReport,
    Trim,
)

Stage = Literal["queued", "decode", "trim", "beats", "snap", "tempo", "meter", "done", "failed"]
STAGES: tuple[Stage, ...] = ("queued", "decode", "trim", "beats", "snap", "tempo", "meter", "done", "failed")
# the stages run_analysis actually runs, so the only ones a StageError can name
RunStage = Literal["decode", "trim", "beats", "snap", "tempo", "meter"]

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
    tempo_range: TempoRange = TempoRange()
    tempo_map: TempoMapConfig = TempoMapConfig()
    meter: MeterConfig = MeterConfig()
    notation: NotationConfig = NotationConfig()


@dataclass(frozen=True)
class AnalysisOutput:
    report: TimingReport
    beats: BeatsFile
    decoded: DecodedAudio
    trim: TrimResult
    tracked: TrackedBeats
    # one per rough tempo segment
    octave: list[OctaveCheck]
    snap: SnapResult
    # with each segment's anchor on beat 1 of the meter
    tempo: TempoMapResult
    meter: MeterResult
    features: GridFeatures
    suggestions: list[Suggestion]


def _ms(value: float) -> float:
    # sub-microsecond digits are noise at 44.1 khz (one sample is ~0.023 ms), round so the json stays readable
    return round(float(value), 3)


def tempo_segments(tempo: TempoMapResult) -> list[TempoSegment]:
    segments = [
        TempoSegment(
            start_ms=_ms(s.start_ms),
            end_ms=_ms(s.end_ms),
            bpm=round(s.fit.bpm, 4),
            anchor_ms=_ms(s.anchor_ms),
            confidence=round(s.fit.confidence, 3),
            source="auto",
            ratio_merged=[
                RatioMergedSection(
                    start_ms=_ms(m.start_ms),
                    end_ms=_ms(m.end_ms),
                    bpm=round(m.bpm, 4),
                    ratio=f"{m.ratio.numerator}/{m.ratio.denominator}",
                    fit=round(m.fit, 3),
                )
                for m in s.ratio_merges
            ],
        )
        # each end is the same float as the next start, so they round the same and stay contiguous
        for s in tempo.segments
    ]
    return segments


def meter_segments(meter: MeterResult) -> list[MeterSegment]:
    # meter boundaries on a tempo segment's start are the same float as that start, so they round the same
    return [
        MeterSegment(
            start_ms=_ms(r.start_ms),
            end_ms=_ms(r.end_ms),
            numerator=r.numerator,
            denominator=r.denominator,
            confidence=round(r.confidence, 3),
            source="auto",
        )
        for r in meter.runs
    ]


def notation_suggestions(suggestions: list[Suggestion]) -> list[NotationSuggestion]:
    return [
        NotationSuggestion(
            start_ms=_ms(s.start_ms),
            end_ms=_ms(s.end_ms),
            kind=s.kind,
            suggested_bpm=round(s.suggested_bpm, 4),
            grid_bpm=round(s.grid_bpm, 4),
            score=round(min(1.0, max(0.0, s.score)), 3),
        )
        for s in sorted(suggestions, key=lambda s: s.start_ms)
    ]


def build_report(
    filename: str,
    sha256: str,
    decoded: DecodedAudio,
    trim: TrimResult,
    tempo: TempoMapResult,
    previous: TimingReport | None = None,
    meter: MeterResult | None = None,
    suggestions: list[Suggestion] | None = None,
) -> TimingReport:
    tempo_map = tempo_segments(tempo)
    meter_map = meter_segments(meter) if meter is not None else []
    notes = notation_suggestions(suggestions or [])
    edits = []
    if previous is not None:
        # re-analysis: manual segments stay exactly as they were, and so does the edit log.
        # applied and dismissed suggestions are decisions too, they stay and aren't suggested again
        tempo_map = keep_manual_segments(previous.tempo_map, tempo_map)
        meter_map = keep_manual_meter(previous.meter_map, meter_map)
        notes = keep_decided(previous.notation_suggestions, notes, tempo_map)
        edits = list(previous.edits)
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
        # the first segment starts at the first sound, its anchor is the first downbeat
        tempo_map=tempo_map,
        meter_map=meter_map,
        # from this analysis, manual edits don't move them and a re-analysis replaces them
        offbeat_runs=[
            OffbeatRun(start_ms=_ms(r.start_ms), end_ms=_ms(r.end_ms), beats=r.beats)
            for seg in tempo.segments
            for r in seg.offbeat_runs
        ],
        notation_suggestions=notes,
        edits=edits,
    )


def _feature_number(value: float) -> float:
    # four significant figures, the detector only ever compares them with each other
    return float(f"{value:.4g}")


def build_beats_file(
    sha256: str,
    tracked: TrackedBeats,
    octave: list[OctaveCheck],
    snap: SnapResult,
    tempo: TempoMapResult,
    features: GridFeatures | None = None,
) -> BeatsFile:
    if tracked.downbeats_known:
        positions = tracked.positions
    else:
        # librosa's guess, counted on each segment's grid so a dropped beat doesn't slip the bar
        positions = tempo.indices % FALLBACK_BEATS_PER_BAR + 1
    bars = bar_numbers(positions)
    beats = [
        Beat(
            # snap can land a fraction of a ms before 0 on audio that starts with a hit
            time_ms=max(0.0, _ms(snap.times_ms[i])),
            raw_time_ms=max(0.0, _ms(tracked.times_ms[i])),
            residual_ms=_ms(tempo.residuals_ms[i]),
            bar=int(bars[i]),
            beat_in_bar=int(positions[i]),
            is_downbeat=bool(positions[i] == 1),
        )
        for i in range(len(tracked.times_ms))
    ]
    stored = []
    if features is not None:
        stored = [
            GridFeature(
                time_ms=max(0.0, _ms(t)),
                low=_feature_number(v[0]),
                mid=_feature_number(v[1]),
                high=_feature_number(v[2]),
            )
            for t, v in zip(features.times_ms, features.values)
        ]
    return BeatsFile(sha256=sha256, tracker=tracked.tracker, octave=summary(octave), beats=beats, grid_features=stored)


def run_analysis(
    original_path: Path,
    work_dir: Path,
    filename: str,
    sha256: str,
    on_stage: Callable[[RunStage], None] | None = None,
    config: AnalysisConfig = AnalysisConfig(),
    previous: TimingReport | None = None,
) -> AnalysisOutput:
    """Run every stage on one file. With previous (re-analysis), its manual segments and edits carry over."""
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
        tracked = track_beats(samples, sample_rate, trim.start_ms, trim.end_ms, tracker=config.tracker, tempo_range=config.tempo_range)
        # the tracker's bias comes out before anything reads onsets around its beats
        shift = bias_correction_ms(tracked.tracker)
        # rough segments from the raw beats first, so a section the tracker took at half
        # time gets its own octave check instead of being outvoted by the rest of the song.
        # not consolidated, a half time section would get folded in by the ratio check
        rough = build_tempo_map(
            tracked.times_ms + shift,
            tracked.positions == 1,
            trim.start_ms,
            trim.end_ms,
            downbeats_known=tracked.downbeats_known,
            config=config.tempo_map,
            consolidate=False,
        )
        ranges = [(s.first, s.stop) for s in rough.segments]
        tracked, octave = check_octave_per_segment(
            samples,
            sample_rate,
            tracked,
            ranges,
            config.tempo_range,
            shift_ms=shift,
            rough_bpm=[s.fit.bpm for s in rough.segments],
            ratio_tolerance=config.tempo_map.ratio_tolerance,
        )

        enter("snap")
        snap = snap_to_onsets(samples, sample_rate, tracked.times_ms, window_ms=config.snap_window_ms, shift_ms=shift)

        enter("tempo")
        tempo = build_tempo_map(
            snap.times_ms,
            tracked.positions == 1,
            trim.start_ms,
            trim.end_ms,
            downbeats_known=tracked.downbeats_known,
            config=config.tempo_map,
            loudness=stretch_level(samples, sample_rate, trim.start_ms, trim.end_ms),
            onsets=lambda times: onset_strengths(samples, sample_rate, times),
        )

        enter("meter")
        # band strengths on every line and half line of the map, what meter and notation read.
        # they go in the beats file so the suggestions can be checked again without the audio
        flux = band_flux(samples, sample_rate, trim.start_ms, trim.end_ms)
        features = grid_features(flux, feature_positions(from_fits(tempo.segments), trim.start_ms, trim.end_ms, config.tempo_map))
        meter = infer_meter(
            tempo,
            snap.times_ms,
            tracked.positions == 1,
            accents=lambda times: features.lookup(times).sum(axis=1),
            config=config.meter,
        )
        tempo = meter.tempo
        segments = from_fits(tempo.segments)
        suggestions = feel_suggestions(segments, meter.runs, features, config.notation) + fold_suggestions(
            segments, features, trim.start_ms, trim.end_ms, config.tempo_map, config.notation
        )
    except Exception as exc:
        # keep whatever the stage said, the ui shows it as is
        raise StageError(stage, str(exc) or type(exc).__name__) from exc

    report = build_report(filename, sha256, decoded, trim, tempo, previous, meter, suggestions)
    beats = build_beats_file(sha256, tracked, octave, snap, tempo, features)
    return AnalysisOutput(
        report=report,
        beats=beats,
        decoded=decoded,
        trim=trim,
        tracked=tracked,
        octave=octave,
        snap=snap,
        tempo=tempo,
        meter=meter,
        features=features,
        suggestions=suggestions,
    )


def snap_shift_ms(tracked: TrackedBeats, snap: SnapResult) -> float:
    # median move from the raw tracker beat to where it snapped, bias correction included.
    # on real songs this is the number to compare against MADMOM_BIAS_MS
    moved = snap.times_ms[snap.snapped] - tracked.times_ms[snap.snapped]
    return float(np.median(moved)) if len(moved) else 0.0
