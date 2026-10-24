"""Applies one tempo edit from PATCH /report and writes what changed into edits.

The edit log has to say exactly what moved. A value edit (bpm, anchor) adds
one entry per field that changed in that segment, the flip to manual and the
dropped confidence included. Split, merge and match change the shape of the
list, so they log the whole tempo_map before and after.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import ValidationError

from backend.analysis import tempo_edit
from backend.analysis.tempo_edit import TempoEditError, TrackedTimes
from backend.api.models import Match, Merge, SetAnchor, SetBpm, Split, TempoEdit
from backend.schema.models import BeatsFile, Edit, TempoSegment, TimingReport


def tracked_times(beats: BeatsFile | None) -> TrackedTimes | None:
    # what split and merge refit from, the snapped times the analysis fitted
    if beats is None or not beats.beats:
        return None
    return TrackedTimes(
        times_ms=np.array([b.time_ms for b in beats.beats]),
        is_downbeat=np.array([b.is_downbeat for b in beats.beats]),
        downbeats_known=beats.tracker == "madmom",
    )


def _segment_edits(index: int, old: TempoSegment, new: TempoSegment, now: datetime) -> list[Edit]:
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return [
        Edit(field=f"tempo_map/{index}/{key}", old=before[key], new=after[key], timestamp=now)
        for key in before
        if before[key] != after[key]
    ]


def apply_tempo_edit(report: TimingReport, body: TempoEdit, beats: BeatsFile | None, now: datetime) -> TimingReport:
    """The report with the edit applied and logged, or the same report when nothing changed.

    Raises TempoEditError when the edit doesn't fit this tempo map.
    """
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
        edits = [
            Edit(
                field="tempo_map",
                old=[s.model_dump(mode="json") for s in old_map],
                new=[s.model_dump(mode="json") for s in new_map],
                timestamp=now,
            )
        ]
    changed = report.model_copy(update={"tempo_map": new_map, "edits": [*report.edits, *edits]})
    # dumped and read back so every segment is checked again. model instances would be taken as
    # they are, and a bpm that rounds to 0 got saved that way and made the report unreadable
    try:
        return TimingReport.model_validate(changed.model_dump())
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(part) for part in error["loc"])
        raise TempoEditError(f"that edit would leave the report invalid, {where}: {error['msg']}") from exc
