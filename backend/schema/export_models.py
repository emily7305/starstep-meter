"""The export file, built from a timing report and never from audio.

TimingExport is the report as it is, plus the beats file when it's asked for.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field
from pydantic.json_schema import JsonDict, SkipJsonSchema

from backend.schema.models import BeatsFile, TimingReport, _Strict


def _beats_optional(schema: JsonDict) -> None:
    # beats only has a default so it can be left out, the backend never writes it as null
    required = schema["required"]
    assert isinstance(required, list)
    required.remove("beats")


class TimingExport(_Strict):
    model_config = ConfigDict(**_Strict.model_config, json_schema_extra=_beats_optional)

    kind: Literal["timing"] = "timing"
    exported_at: AwareDatetime
    report: TimingReport
    # left out unless asked for, a long song has thousands of beats. never null in the file
    beats: BeatsFile | SkipJsonSchema[None] = Field(
        default=None,
        description="the beats file of the same analysis, only there when the export asked for it",
        json_schema_extra=lambda schema: schema.pop("default", None),
    )
