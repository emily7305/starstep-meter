"""Timing report schema v2.0.

All times are milliseconds from the first sample of the decoded audio
(ffmpeg's output, before any trimming). Bars are 0-based, beats inside
a bar are 1-based, so beat_in_bar == 1 is the downbeat.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

SCHEMA_VERSION = "2.0"

# every segment says where it came from, re-analysis only ever replaces "auto"
SegmentSource = Literal["auto", "manual"]


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


class TempoSegment(_Strict):
    start_ms: float = Field(ge=0, description="where this tempo starts, the first segment starts at trim.start_ms")
    end_ms: float = Field(ge=0, description="where it stops, the same value as the next segment's start_ms")
    bpm: float = Field(gt=0)
    # its own phase, so a manual segment carries its whole grid and re-analysis can leave it alone
    anchor_ms: float = Field(
        description="a downbeat on this segment's grid, which is anchor_ms + k * 60000 / bpm. "
        "the first segment's anchor is the song's first downbeat"
    )
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: SegmentSource

    @model_validator(mode="after")
    def _ordered(self) -> TempoSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("tempo segment end_ms has to be after start_ms")
        return self


class MeterSegment(_Strict):
    start_bar: int = Field(ge=0)
    numerator: int = Field(ge=1)
    denominator: int = Field(ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: SegmentSource

    @model_validator(mode="after")
    def _power_of_two(self) -> MeterSegment:
        if self.denominator & (self.denominator - 1):
            raise ValueError("meter denominator must be a power of two")
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


class Edit(_Strict):
    field: str = Field(description="path of the changed value, e.g. tempo_map/0/bpm")
    old: JsonValue
    new: JsonValue
    timestamp: AwareDatetime


class TimingReport(_Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    source: AudioSource
    trim: Trim
    # contiguous, the first downbeat is tempo_map[0].anchor_ms. no player compensation, see docs/decisions.md
    tempo_map: list[TempoSegment] = Field(min_length=1)
    meter_map: list[MeterSegment] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    # append-only, one entry per manual change
    edits: list[Edit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _contiguous(self) -> TimingReport:
        # every moment between the first start and the last end has exactly one tempo
        for prev, nxt in zip(self.tempo_map, self.tempo_map[1:]):
            if nxt.start_ms != prev.end_ms:
                raise ValueError("tempo segments have to be contiguous, each start_ms equal to the previous end_ms")
        return self


class Beat(_Strict):
    time_ms: float = Field(ge=0, description="beat time after onset snap")
    raw_time_ms: float = Field(
        ge=0,
        description="beat time as the tracker reported it, before bias correction and onset snap. "
        "halfway between two tracker beats when the octave check doubled the tempo",
    )
    residual_ms: float = Field(description="time_ms minus its tempo segment's fitted grid at this beat")
    bar: int = Field(ge=0)
    beat_in_bar: int = Field(ge=1)
    is_downbeat: bool


class BeatsFile(_Strict):
    # beats live in their own file next to report.json, a long song has thousands
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="same file as the report it belongs to")
    # librosa is the fallback when madmom isn't installed, it has no downbeats so bars are guessed
    tracker: Literal["madmom", "librosa"]
    octave: Literal["kept", "doubled", "halved", "mixed"] = Field(
        description="what the octave check did to the tracker's tempo, mixed when it differs between "
        "tempo segments, see docs/decisions.md"
    )
    beats: list[Beat] = Field(default_factory=list)
