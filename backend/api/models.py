"""Response bodies for the api."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.pipeline import Stage

# where a job can have broken, done and failed are outcomes, not places
ErrorStage = Literal["queued", "decode", "trim", "beats", "snap", "tempo", "meter", "check"]


class JobError(BaseModel):
    stage: ErrorStage
    message: str


class JobStatus(BaseModel):
    status: Literal["queued", "running", "done", "failed"]
    stage: Stage
    error: JobError | None = None
    # filled in when the status is read, never stored. true for a failed job that still has the
    # last good report from before a failed re-analysis
    report_available: bool = False


class JobCreated(BaseModel):
    job_id: str


class Health(BaseModel):
    status: Literal["ok"]
    ffmpeg: bool
    ffprobe: bool
    # true only when it's installed and imports
    madmom: bool
    # why an installed madmom doesn't import, none when it works or isn't installed
    madmom_error: str | None = None


class JobSummary(BaseModel):
    job_id: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: str
    # when a re-analysis last finished, None when there hasn't been one
    reanalyzed_at: str | None = None
    status: Literal["queued", "running", "done", "failed"]
    # how many manual edits the report holds, None when there's no report to count
    edits: int | None


class _Op(BaseModel):
    # same strictness as the report, a typo'd key should be a 422 and not a silent no-op
    model_config = ConfigDict(extra="forbid")


# strict so "2100" or true is a 422 instead of being read as a number
_Ms = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Index = Annotated[int, Field(strict=True, ge=0)]


class SetAnchor(_Op):
    op: Literal["set_anchor"]
    segment: _Index
    anchor_ms: _Ms


class SetBpm(_Op):
    op: Literal["set_bpm"]
    segment: _Index
    # past 1000 it's a typo, not a tempo
    bpm: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, le=1000)]


class Split(_Op):
    op: Literal["split"]
    at_ms: _Ms


class SplitOut(_Op):
    # splits at both ends of one of the segment's ratio_merged sections, one edit for the two cuts
    op: Literal["split_out"]
    segment: _Index
    section: _Index


class Merge(_Op):
    # merges this segment with the one after it
    op: Literal["merge"]
    segment: _Index


class Match(_Op):
    # this segment takes the previous or next segment's grid and joins it
    op: Literal["match"]
    segment: _Index
    side: Literal["previous", "next"]


class SetMeter(_Op):
    # a meter set by hand, numerator over denominator, for one meter segment
    op: Literal["set_meter"]
    segment: _Index
    numerator: Annotated[int, Field(strict=True, ge=1, le=32)]
    denominator: Literal[1, 2, 4, 8, 16, 32, 64]


class SplitMeter(_Op):
    # a new meter segment from the beat nearest at_ms, bars restart there
    op: Literal["split_meter"]
    at_ms: _Ms


class MergeMeter(_Op):
    op: Literal["merge_meter"]
    segment: _Index


class ApplySuggestion(_Op):
    op: Literal["apply_suggestion"]
    suggestion: _Index


class DismissSuggestion(_Op):
    op: Literal["dismiss_suggestion"]
    suggestion: _Index


TempoEdit = Annotated[
    SetAnchor
    | SetBpm
    | Split
    | SplitOut
    | Merge
    | Match
    | SetMeter
    | SplitMeter
    | MergeMeter
    | ApplySuggestion
    | DismissSuggestion,
    Field(discriminator="op"),
]
