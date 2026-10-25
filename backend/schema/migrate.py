"""Bring a stored report or beats file from an older schema up to the current one.

Works on the parsed json before validation, one version step at a time. 1.1,
2.0, 2.1, 2.2 and 2.3 can be upgraded, 1.0 reports have no codec or decoder padding
and those can only come from the original file, so they still need a fresh upload.
"""

from __future__ import annotations

from typing import Any


def upgrade_report(data: Any) -> Any:
    """A 1.1, 2.0, 2.1, 2.2 or 2.3 report as 2.4. Anything else comes back untouched and fails validation as usual."""
    data = _version_step(_report_2_0_to_2_1(_report_1_1_to_2_0(data)), "2.1", "2.2")
    # 2.3 -> 2.4: no confidence spans and no cross-check, the segment confidences stay as they were
    return _version_step(_report_2_2_to_2_3(data), "2.3", "2.4")


def upgrade_beats(data: Any) -> Any:
    """A 1.1, 2.0, 2.1, 2.2 or 2.3 beats file as 2.4."""
    data = _version_step(_beats_2_0_to_2_1(_beats_1_1_to_2_0(data)), "2.1", "2.2")
    # 2.2 -> 2.3: grid_features defaults to empty, the suggestions just can't be checked without the audio
    data = _version_step(data, "2.2", "2.3")
    # 2.3 -> 2.4: cross_check_beats defaults to empty, the cross-check needs the audio again
    return _version_step(data, "2.3", "2.4")


def _version_step(data: Any, old: str, new: str) -> Any:
    # 2.1 -> 2.2: the report gains offbeat_runs, empty by default, the beats file only moves with it
    if not isinstance(data, dict) or data.get("schema_version") != old:
        return data
    return {**data, "schema_version": new}


def _report_2_2_to_2_3(data: Any) -> Any:
    """2.2 -> 2.3: meter segments go by time instead of bar number, and notation_suggestions starts empty.

    Nothing wrote a meter segment before 2.3, so meter_map is empty and stays empty (4/4 from each
    tempo segment's anchor, as it was drawn). One written by hand has no time to go by and is left
    as it was, so it fails validation instead of landing somewhere it wasn't meant to.
    """
    return _version_step(data, "2.2", "2.3")


def _report_1_1_to_2_0(data: Any) -> Any:
    """1.1 -> 2.0: beat_offset_ms becomes the first segment's anchor, segments get an end.

    The edit log stays as it was, entries for beat_offset_ms describe what is now
    tempo_map/0/anchor_ms.
    """
    if not isinstance(data, dict) or data.get("schema_version") != "1.1":
        return data
    out = dict(data)
    offset = out.pop("beat_offset_ms", None)
    trim = out.get("trim") or {}
    duration = (out.get("source") or {}).get("duration_ms")
    old_map = list(out.get("tempo_map") or [])
    tempo_map = []
    for i, seg in enumerate(old_map):
        seg = dict(seg)
        if i + 1 < len(old_map):
            seg["end_ms"] = old_map[i + 1]["start_ms"]
        else:
            # a 1.1 report always had one segment from the trim start, so it ends at the trim end
            end = trim.get("end_ms")
            seg["end_ms"] = end if end is not None and end > seg["start_ms"] else duration
        # later segments never existed in 1.1 in practice, their start is the only phase there is
        seg["anchor_ms"] = offset if i == 0 and offset is not None else seg["start_ms"]
        tempo_map.append(seg)
    out["tempo_map"] = tempo_map
    out["schema_version"] = "2.0"
    return out


def _report_2_0_to_2_1(data: Any) -> Any:
    # 2.0 -> 2.1: nothing was ratio merged yet, and ratio_merged defaults to empty
    if not isinstance(data, dict) or data.get("schema_version") != "2.0":
        return data
    return {**data, "schema_version": "2.1"}


def _beats_1_1_to_2_0(data: Any) -> Any:
    # 1.1 -> 2.0: there was no octave check yet, so nothing was doubled or halved
    if not isinstance(data, dict) or data.get("schema_version") != "1.1":
        return data
    return {**data, "schema_version": "2.0", "octave": "kept"}


def _beats_2_0_to_2_1(data: Any) -> Any:
    # 2.0 -> 2.1: same fields, the version moves with the report's
    if not isinstance(data, dict) or data.get("schema_version") != "2.0":
        return data
    return {**data, "schema_version": "2.1"}
