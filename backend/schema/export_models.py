"""The two export files, both built from a timing report and never from audio.

TimingExport is the plain one: the report as it is, plus the beats file when it's
asked for. SonolusExport holds the values a Sonolus level needs, worked out from
the tempo map and the meter map (see backend/analysis/sonolus.py and the Sonolus
section of docs/decisions.md).
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


class SonolusDataValue(_Strict):
    name: str
    value: float


class SonolusEntity(_Strict):
    archetype: str
    data: list[SonolusDataValue]


class SonolusLevelData(_Strict):
    # field names are Sonolus' own (LevelData in @sonolus/core), hence the camel case
    bgmOffset: float = Field(
        description="seconds into the bgm file at level time 0, which is beat 0. the bgm is at level time + bgmOffset"
    )
    entities: list[SonolusEntity] = Field(
        description="one #BPM_CHANGE per tempo, with #BEAT and #BPM. an engine's own entities (initialization, "
        "stage, notes) go next to these"
    )


class SonolusBpmChange(_Strict):
    beat: float = Field(ge=0)
    bpm: float = Field(gt=0)
    time_ms: float = Field(
        description="where the change is on the report's timeline (ffmpeg's decode), before decoder compensation"
    )


class SonolusTimeSignature(_Strict):
    beat: float = Field(ge=0, description="the bar line this signature starts on")
    numerator: int = Field(ge=1)
    denominator: int = Field(ge=1, le=64)


class SonolusExport(_Strict):
    kind: Literal["sonolus"] = "sonolus"
    exported_at: AwareDatetime
    filename: str = Field(description="the report's source filename, for display only")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="the source file the report belongs to")
    decoder_compensation_ms: float = Field(
        description="how much later than ffmpeg's timeline the player's decoder plays the audio, already in bgmOffset"
    )
    first_downbeat_beat: float = Field(ge=0, description="the beat of tempo_map[0].anchor_ms, the song's first downbeat")
    level_data: SonolusLevelData
    bpm_changes: list[SonolusBpmChange] = Field(min_length=1, description="the same changes as level_data, with times")
    time_signatures: list[SonolusTimeSignature] = Field(
        min_length=1,
        description="not part of Sonolus level data, which has no time signature archetype. for the chart editor. "
        "a bar cut short by a tempo change or a meter split gets its own entry",
    )
