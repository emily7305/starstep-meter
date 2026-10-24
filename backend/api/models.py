"""Response bodies for the api."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.pipeline import Stage

# where a job can have broken, done and failed are outcomes, not places
ErrorStage = Literal["queued", "decode", "trim", "beats", "snap", "tempo"]


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


class Merge(_Op):
    # merges this segment with the one after it
    op: Literal["merge"]
    segment: _Index


class Match(_Op):
    # this segment takes the previous or next segment's grid and joins it
    op: Literal["match"]
    segment: _Index
    side: Literal["previous", "next"]


TempoEdit = Annotated[SetAnchor | SetBpm | Split | Merge | Match, Field(discriminator="op")]
