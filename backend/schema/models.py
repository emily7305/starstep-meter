"""Timing report schema v2.6.

All times are milliseconds from the first sample of the decoded audio
(ffmpeg's output, before any trimming). Bars are 0-based, beats inside
a bar are 1-based, so beat_in_bar == 1 is the downbeat.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

SCHEMA_VERSION = "2.6"

# every segment says where it came from, re-analysis only ever replaces "auto"
SegmentSource = Literal["auto", "manual"]

# x2 and /2 applied up to three times either way, exact in binary so they compare with ==
NOTATION_SCALES = (0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


class _Strict(BaseModel):
    # typos in hand-edited reports should fail loudly, not vanish
    # defaults count as required in the exported schema since the backend always writes them
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class AudioSource(_Strict):
    filename: str = Field(description="original upload name, for display only")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="sha256 of the original file, not the decoded wav")
    duration_ms: float = Field(ge=0, description="length of the decoded audio")
    sample_rate: int = Field(gt=0, description="sample rate of the decoded audio in Hz")
    codec: str = Field(description="codec of the first audio stream as ffprobe names it, e.g. mp3, aac, vorbis")
    decoder_padding_samples: int = Field(
        ge=0,
        description="samples a decoder that ignores gapless info plays before ffmpeg's first sample, 0 if not applicable",
    )


class Trim(_Strict):
    start_ms: float = Field(ge=0, description="first audible sound")
    end_ms: float = Field(ge=0, description="end of the last audible sound")

    @model_validator(mode="after")
    def _ordered(self) -> Trim:
        if self.end_ms < self.start_ms:
            raise ValueError("trim end_ms is before start_ms")
        return self


class RatioMergedSection(_Strict):
    # a stretch the ratio check folded into its segment, kept so it can be split back out
    start_ms: float = Field(ge=0)
    end_ms: float = Field(ge=0)
    bpm: float = Field(gt=0, description="what the stretch fitted to on its own")
    ratio: str = Field(
        pattern=r"^[1-9][0-9]*/[1-9][0-9]*$",
        description="its bpm over the segment's, near enough, e.g. 3/4 for a triplet feel or 2/3 for a dotted one",
    )
    fit: float = Field(
        ge=0,
        description="share of its beats on the segment's grid (lines, halves, thirds) over the share on its own grid",
    )

    @model_validator(mode="after")
    def _ordered(self) -> RatioMergedSection:
        if self.end_ms <= self.start_ms:
            raise ValueError("ratio merged end_ms has to be after start_ms")
        return self


class TempoSegment(_Strict):
    start_ms: float = Field(ge=0, description="where this tempo starts, the first segment starts at trim.start_ms")
    end_ms: float = Field(ge=0, description="where it stops, the same value as the next segment's start_ms")
    bpm: float = Field(gt=0)
    # its own phase, so a manual segment carries its whole grid and re-analysis can leave it alone
    anchor_ms: float = Field(
        description="a downbeat on this segment's grid, which is anchor_ms + k * 60000 / bpm. "
        "the first segment's anchor is the song's first downbeat"
    )
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="residual share times cross-check agreement over the segment, like confidence_spans, halved "
        "for the librosa fallback. a refit after a split or merge has the refit's residual share only, null when "
        "the bpm or anchor was set by hand",
    )
    source: SegmentSource
    # x2 and /2 are how a chart writes the pulse, not a correction of the analysis, so they don't make
    # a segment manual. re-analysis puts the same factor on the new auto segment
    notation_scale: float = Field(
        default=1.0,
        description="the bpm over the analysis' own bpm for this stretch when only x2 or /2 was applied, a power of "
        "two from 1/8 to 8. 1 for a segment as analyzed and for a manual one, whose bpm was set by hand",
    )
    ratio_merged: list[RatioMergedSection] = Field(
        default_factory=list,
        description="felt tempo sections (dotted, triplet feel) inside this segment that the analysis kept "
        "on its grid, splitting at a section's start_ms and end_ms gives it back its own tempo",
    )

    @model_validator(mode="after")
    def _ordered(self) -> TempoSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("tempo segment end_ms has to be after start_ms")
        if self.notation_scale not in NOTATION_SCALES:
            raise ValueError("notation_scale has to be a power of two from 1/8 to 8")
        for note in self.ratio_merged:
            if note.start_ms < self.start_ms or note.end_ms > self.end_ms:
                raise ValueError("a ratio merged section has to be inside its tempo segment")
        return self


class MeterSegment(_Strict):
    # by time, not by bar number. halving a span's bpm or splitting a segment renumbers every bar
    # after it, and a manual meter has to stay where it was put
    start_ms: float = Field(
        ge=0,
        description="where this meter starts, the first starts at tempo_map[0].start_ms. inside a tempo segment "
        "it's a bar line and bars restart there, at a tempo segment's start the segment's anchor is bar 1",
    )
    end_ms: float = Field(ge=0, description="where it stops, the same value as the next meter segment's start_ms")
    numerator: int = Field(ge=1, le=32)
    # a bar is numerator * 4 / denominator beats of the tempo segment's grid, the bpm counts quarter notes
    denominator: int = Field(ge=1, le=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: SegmentSource

    @model_validator(mode="after")
    def _checked(self) -> MeterSegment:
        if self.denominator & (self.denominator - 1):
            raise ValueError("meter denominator must be a power of two")
        if self.end_ms <= self.start_ms:
            raise ValueError("meter segment end_ms has to be after start_ms")
        return self


class Section(_Strict):
    label: str
    start_ms: float = Field(ge=0)
    end_ms: float = Field(ge=0)
    source: SegmentSource

    @model_validator(mode="after")
    def _ordered(self) -> Section:
        if self.end_ms < self.start_ms:
            raise ValueError("section end_ms is before start_ms")
        return self


class OffbeatRun(_Strict):
    # where the tracker followed the off-beat for a while, the grid stays on the beats there
    start_ms: float = Field(ge=0, description="first tracked beat of the run")
    end_ms: float = Field(ge=0, description="last tracked beat of the run")
    beats: int = Field(ge=1, description="tracked beats in the run")

    @model_validator(mode="after")
    def _ordered(self) -> OffbeatRun:
        if self.end_ms < self.start_ms:
            raise ValueError("off-beat run end_ms is before start_ms")
        return self


class ConfidenceSpan(_Strict):
    # a stretch of a tempo segment, window_beats long on its grid, see backend/analysis/confidence.py
    start_ms: float = Field(ge=0)
    end_ms: float = Field(ge=0)
    confidence: float = Field(
        ge=0, le=1, description="residual_share * (1 - w + w * agreement), w = 0.5, or residual_share without a cross-check"
    )
    residual_share: float | None = Field(
        ge=0,
        le=1,
        description="share of its tracked beats within 10 ms of the grid, a felt section's beats count as min(1, fit). "
        "off-beat runs and their ramps are left out, null when that leaves nothing",
    )
    agreement: float | None = Field(
        ge=0, le=1, description="share of compared beats where the second tracker had one close by, null without one"
    )
    low: bool = Field(description="under the threshold the timeline shades at")

    @model_validator(mode="after")
    def _ordered(self) -> ConfidenceSpan:
        if self.end_ms <= self.start_ms:
            raise ValueError("confidence span end_ms has to be after start_ms")
        return self


class CrossCheckSegment(_Strict):
    start_ms: float = Field(ge=0)
    end_ms: float = Field(ge=0)
    disagreement_ms: float | None = Field(
        ge=0, description="median distance between the two trackers' beats, null with too few beats to compare"
    )
    compared: int = Field(ge=0, description="beats compared, felt sections and off-beat runs left out")
    flagged: bool = Field(description="disagreement_ms is over max_disagreement_ms")


class CrossCheck(_Strict):
    # a second beat tracker on the same audio, compared per tempo segment of the analysis
    tracker: Literal["librosa"]
    max_disagreement_ms: float = Field(gt=0)
    segments: list[CrossCheckSegment] = Field(
        default_factory=list, description="one per tempo segment the analysis found, not following later edits"
    )


NotationKind = Literal["half", "double", "fold", "shift"]
SuggestionStatus = Literal["open", "applied", "dismissed"]


class NotationSuggestion(_Strict):
    # the audio can't say how a chart writes a pulse, so these are only ever applied by hand
    start_ms: float = Field(ge=0, description="a bar line, or the start of the tempo segment for a fold")
    end_ms: float = Field(ge=0)
    kind: NotationKind = Field(
        description="half: the span feels like half the grid's tempo, double: twice it, "
        "fold: a first or last stretch that may be its neighbour's tempo the analysis didn't fold in, "
        "shift: the downbeat may move at start_ms, the tracker's bars restarted there after one short bar the "
        "meter left out. applying it restarts the bars at start_ms, suggested_bpm is the grid's own then"
    )
    suggested_bpm: float = Field(gt=0)
    grid_bpm: float = Field(gt=0, description="bpm of the tempo segment the suggestion was made on")
    score: float = Field(ge=0, le=1, description="how clear the evidence is, 1 is as clear as it gets")
    # applied and dismissed are manual decisions, kept through re-analysis like manual segments
    status: SuggestionStatus = "open"

    @model_validator(mode="after")
    def _ordered(self) -> NotationSuggestion:
        if self.end_ms <= self.start_ms:
            raise ValueError("suggestion end_ms has to be after start_ms")
        return self


SubdivisionKind = Literal["swing", "gallop", "reverse_gallop"]


class SubdivisionSection(_Strict):
    # where the notes between the beats are uneven, read on the grid as it is and never applied
    start_ms: float = Field(ge=0, description="a bar line, or the start of the tempo segment")
    end_ms: float = Field(ge=0, description="a bar line, or the end of the tempo segment")
    kind: SubdivisionKind = Field(
        description="swing: long-short 8ths, gallop: 8th-16th-16th, reverse_gallop: 16th-16th-8th, "
        "the gallops on a straight or a triplet base"
    )
    ratio: float = Field(
        gt=0, description="the long note over the short one, 2 for a 2:1 swing or a straight gallop, 4 for a triplet gallop"
    )
    division: int = Field(
        ge=1,
        description="notes per 4/4 measure a chart editor needs for them at grid_bpm, 12 is 1/12. "
        "twice that with the bpm halved",
    )
    grid_bpm: float = Field(gt=0, description="bpm of the tempo segment it was read on")
    score: float = Field(ge=0, le=1, description="how clear the notes and the empty positions are, 1 is as clear as it gets")

    @model_validator(mode="after")
    def _ordered(self) -> SubdivisionSection:
        if self.end_ms <= self.start_ms:
            raise ValueError("subdivision section end_ms has to be after start_ms")
        return self


class Edit(_Strict):
    # one manual change is one entry, however many values it touched
    field: str = Field(
        description="the deepest path that holds everything the change touched, e.g. tempo_map/0/bpm. "
        "with one changed value old and new are that value, with several they're objects keyed by each "
        "value's path under field, and an empty field is the report itself"
    )
    old: JsonValue
    new: JsonValue
    timestamp: AwareDatetime


class AutoResult(_Strict):
    # what the latest analysis found on its own, before the manual segments were put back
    tempo_map: list[TempoSegment] = Field(min_length=1, description="every segment auto, notation_scale 1")
    meter_map: list[MeterSegment] = Field(default_factory=list)


class TimingReport(_Strict):
    schema_version: Literal["2.6"] = SCHEMA_VERSION
    source: AudioSource
    trim: Trim
    # contiguous, the first downbeat is tempo_map[0].anchor_ms. no player compensation, see docs/decisions.md
    tempo_map: list[TempoSegment] = Field(min_length=1)
    # contiguous over the tempo map's extent, empty means 4/4 from every tempo segment's anchor
    meter_map: list[MeterSegment] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    offbeat_runs: list[OffbeatRun] = Field(
        default_factory=list,
        description="stretches where the analysis found the tracked beats half a beat off the tempo map's grid. "
        "the grid is on the real beats there, the tracker followed the off-beat. analysis output, edits don't change it",
    )
    notation_suggestions: list[NotationSuggestion] = Field(
        default_factory=list,
        description="places where a chart may write the pulse at another tempo (half or double time feel) or "
        "fold an edge into its neighbour. never applied by the analysis, an edit applies or dismisses each one",
    )
    subdivision_sections: list[SubdivisionSection] = Field(
        default_factory=list,
        description="stretches where the notes between the beats are uneven (swing, gallop), with the division a "
        "chart editor needs for them. suggestions only, nothing applies them. analysis output, edits don't change "
        "it and a re-analysis replaces it",
    )
    confidence_spans: list[ConfidenceSpan] = Field(
        default_factory=list,
        description="confidence over stretches of the auto tempo segments, sorted by time. analysis output, "
        "edits don't change it and a re-analysis replaces it",
    )
    cross_check: CrossCheck | None = Field(
        default=None, description="the second tracker's verdict per tempo segment, null when it didn't run"
    )
    auto_result: AutoResult | None = Field(
        default=None,
        description="the tempo and meter map the latest analysis gave without any manual segment, for comparing a "
        "manual segment with and for reset to auto. analysis output, null in a report upgraded from before 2.6",
    )
    # append-only, one entry per manual change
    edits: list[Edit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _contiguous(self) -> TimingReport:
        # every moment between the first start and the last end has exactly one tempo, and one meter
        for prev, nxt in zip(self.tempo_map, self.tempo_map[1:]):
            if nxt.start_ms != prev.end_ms:
                raise ValueError("tempo segments have to be contiguous, each start_ms equal to the previous end_ms")
        for prev_m, nxt_m in zip(self.meter_map, self.meter_map[1:]):
            if nxt_m.start_ms != prev_m.end_ms:
                raise ValueError("meter segments have to be contiguous, each start_ms equal to the previous end_ms")
        return self


class Beat(_Strict):
    time_ms: float = Field(ge=0, description="beat time after onset snap")
    raw_time_ms: float = Field(
        ge=0,
        description="beat time as the tracker reported it, before bias correction and onset snap. "
        "halfway between two tracker beats when the octave check doubled the tempo",
    )
    residual_ms: float = Field(
        description="time_ms minus its tempo segment's fitted grid at this beat. a beat in a ratio merged section "
        "or an off-beat run is measured against the subdivision it sits on, half a beat for an off-beat run"
    )
    bar: int = Field(ge=0)
    beat_in_bar: int = Field(ge=1)
    is_downbeat: bool


class GridFeature(_Strict):
    # onset strength in three bands at one grid position, all on one scale per song so bands compare.
    # numbers about the timing only, there's no way back to the audio from these
    time_ms: float = Field(ge=0, description="a grid line or half line of the analysis' tempo map")
    low: float = Field(ge=0, description="30-150 hz, kick and bass attacks")
    mid: float = Field(ge=0, description="150-3000 hz, snare body and most other attacks")
    high: float = Field(ge=0, description="5-16 khz, hats, cymbals and the snare's noise")


class BeatsFile(_Strict):
    # beats live in their own file next to report.json, a long song has thousands
    schema_version: Literal["2.6"] = SCHEMA_VERSION
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="same file as the report it belongs to")
    # librosa is the fallback when madmom isn't installed, it has no downbeats so bars are guessed
    tracker: Literal["madmom", "librosa"]
    octave: Literal["kept", "doubled", "halved", "mixed"] = Field(
        description="what the octave check did to the tracker's tempo, mixed when it differs between "
        "tempo segments, see docs/decisions.md"
    )
    beats: list[Beat] = Field(default_factory=list)
    grid_features: list[GridFeature] = Field(
        default_factory=list,
        description="band onset strengths at every grid line and half line of the analysis' tempo map, plus the "
        "lines the fold check carried into an edge stretch, sorted by time. what the notation suggestions are "
        "worked out from, so they can be checked again without the audio",
    )
    cross_check_beats: list[float] = Field(
        default_factory=list,
        description="the second tracker's beats after onset snap, in ms, empty when it didn't run. timing only, "
        "the cross-check and the confidence can be worked out again from them without the audio",
    )
