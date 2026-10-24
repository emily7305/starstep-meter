"""Applies one edit from PATCH /report and writes what changed into edits.

The edit log has to say exactly what moved. A value edit (bpm, anchor, a meter's
signature) adds one entry per field that changed in that segment, the flip to
manual and the dropped confidence included. Split, merge and match change the
shape of a list, so they log the whole tempo_map or meter_map before and after.
Applying a suggestion logs the tempo_map before and after and the suggestion's
status, dismissing one only its status.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import ValidationError

from backend.analysis import meter_edit, notation_edit, tempo_edit
from backend.analysis.meter_edit import MeterEditError
from backend.analysis.notation_edit import SuggestionError
from backend.analysis.tempo_edit import TempoEditError, TrackedTimes
from backend.api.models import (
    ApplySuggestion,
    DismissSuggestion,
    Match,
    Merge,
    MergeMeter,
    SetAnchor,
    SetBpm,
    SetMeter,
    Split,
    SplitMeter,
    TempoEdit,
)
from backend.schema.models import BeatsFile, Edit, MeterSegment, TempoSegment, TimingReport


def tracked_times(beats: BeatsFile | None) -> TrackedTimes | None:
    # what split and merge refit from, the snapped times the analysis fitted
    if beats is None or not beats.beats:
        return None
    return TrackedTimes(
        times_ms=np.array([b.time_ms for b in beats.beats]),
        is_downbeat=np.array([b.is_downbeat for b in beats.beats]),
        downbeats_known=beats.tracker == "madmom",
    )


def _segment_edits(
    index: int, old: TempoSegment | MeterSegment, new: TempoSegment | MeterSegment, now: datetime, path: str = "tempo_map"
) -> list[Edit]:
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return [
        Edit(field=f"{path}/{index}/{key}", old=before[key], new=after[key], timestamp=now)
        for key in before
        if before[key] != after[key]
    ]


def _whole(path: str, old: list, new: list, now: datetime) -> Edit:
    return Edit(field=path, old=[s.model_dump(mode="json") for s in old], new=[s.model_dump(mode="json") for s in new], timestamp=now)


def _validated(changed: TimingReport) -> TimingReport:
    # dumped and read back so every segment is checked again. model instances would be taken as
    # they are, and a bpm that rounds to 0 got saved that way and made the report unreadable
    try:
        return TimingReport.model_validate(changed.model_dump())
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        raise TempoEditError(f"that edit would leave the report invalid, {where}: {error['msg']}") from exc


def _meter_edit(report: TimingReport, body: SetMeter | SplitMeter | MergeMeter, now: datetime) -> TimingReport:
    # a report from before 2.3 has no meter map, it's 4/4 all the way and the first edit writes that down
    old_map = meter_edit.meter_or_default(report.meter_map, report.tempo_map)
    try:
        if isinstance(body, SetMeter):
            new_map = meter_edit.set_meter(old_map, body.segment, body.numerator, body.denominator)
        elif isinstance(body, SplitMeter):
            new_map = meter_edit.split_meter(old_map, report.tempo_map, body.at_ms)
        else:
            new_map = meter_edit.merge_meter(old_map, body.segment)
    except MeterEditError as exc:
        raise TempoEditError(str(exc)) from exc
    if new_map == report.meter_map:
        return report
    if isinstance(body, SetMeter) and old_map == report.meter_map:
        edits = _segment_edits(body.segment, old_map[body.segment], new_map[body.segment], now, "meter_map")
    else:
        edits = [_whole("meter_map", report.meter_map, new_map, now)]
    return _validated(report.model_copy(update={"meter_map": new_map, "edits": [*report.edits, *edits]}))


def _suggestion_edit(report: TimingReport, body: ApplySuggestion | DismissSuggestion, now: datetime) -> TimingReport:
    suggestions = report.notation_suggestions
    index = body.suggestion
    if not 0 <= index < len(suggestions):
        raise TempoEditError(f"no suggestion {index}, there are {len(suggestions)}")
    if suggestions[index].status != "open":
        raise TempoEditError(f"suggestion {index} was already {suggestions[index].status}")
    status = "applied" if isinstance(body, ApplySuggestion) else "dismissed"
    edits = []
    tempo_map = report.tempo_map
    if isinstance(body, ApplySuggestion):
        try:
            tempo_map = notation_edit.apply_suggestion(report.tempo_map, suggestions, index)
        except SuggestionError as exc:
            raise TempoEditError(str(exc)) from exc
        edits.append(_whole("tempo_map", report.tempo_map, tempo_map, now))
    edits.append(Edit(field=f"notation_suggestions/{index}/status", old="open", new=status, timestamp=now))
    marked = list(suggestions)
    marked[index] = suggestions[index].model_copy(update={"status": status})
    changed = report.model_copy(update={"tempo_map": tempo_map, "notation_suggestions": marked, "edits": [*report.edits, *edits]})
    return _validated(changed)


def apply_tempo_edit(report: TimingReport, body: TempoEdit, beats: BeatsFile | None, now: datetime) -> TimingReport:
    """The report with the edit applied and logged, or the same report when nothing changed.

    Raises TempoEditError when the edit doesn't fit this report.
    """
    if isinstance(body, (SetMeter, SplitMeter, MergeMeter)):
        return _meter_edit(report, body, now)
    if isinstance(body, (ApplySuggestion, DismissSuggestion)):
        return _suggestion_edit(report, body, now)
    old_map = report.tempo_map
    if isinstance(body, SetAnchor):
        # same rounding as the pipeline, float steps of 1 ms pick up noise in the last digits
        new_map = tempo_edit.set_anchor(old_map, body.segment, round(body.anchor_ms, 3))
    elif isinstance(body, SetBpm):
        # x2 then /2 has to land back where it started, so only the float noise is cut
        new_map = tempo_edit.set_bpm(old_map, body.segment, round(body.bpm, 6))
    elif isinstance(body, Split):
        new_map = tempo_edit.split(old_map, body.at_ms, tracked_times(beats))
    elif isinstance(body, Merge):
        new_map = tempo_edit.merge(old_map, body.segment, tracked_times(beats))
    elif isinstance(body, Match):
        new_map = tempo_edit.match(old_map, body.segment, body.side)
    else:  # pragma: no cover, the union is closed
        raise TypeError(f"unknown tempo edit {body!r}")

    if new_map == old_map:
        return report
    if isinstance(body, (SetAnchor, SetBpm)):
        edits = _segment_edits(body.segment, old_map[body.segment], new_map[body.segment], now)
    else:
        edits = [_whole("tempo_map", old_map, new_map, now)]
    return _validated(report.model_copy(update={"tempo_map": new_map, "edits": [*report.edits, *edits]}))
