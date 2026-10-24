"""Response bodies for the api."""

from __future__ import annotations

from typing import Literal

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


class JobCreated(BaseModel):
    job_id: str


class Health(BaseModel):
    status: Literal["ok"]
    ffmpeg: bool
    ffprobe: bool
    madmom: bool


class OffsetEdit(BaseModel):
    # same strictness as the report, a typo'd key should be a 422 and not a silent no-op
    model_config = ConfigDict(extra="forbid")

    # strict so "2100" or true is a 422 instead of being read as a number
    beat_offset_ms: float = Field(strict=True, allow_inf_nan=False)
