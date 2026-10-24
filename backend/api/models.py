"""Response bodies for the api."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
