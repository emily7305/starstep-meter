"""Bring a stored report or beats file from an older schema up to the current one.

Works on the parsed json before validation, one version step at a time. 1.1,
2.0, 2.1, 2.2, 2.3, 2.4 and 2.5 can be upgraded, 1.0 reports have no codec or decoder padding
and those can only come from the original file, so they still need a fresh upload.
"""

from __future__ import annotations

import math
from typing import Any

# x2 and /2 up to three times either way, the same as models.NOTATION_SCALES
_SCALES = (0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


def upgrade_report(data: Any) -> Any:
    """A 1.1 to 2.5 report as 2.6. Anything else comes back untouched and fails validation as usual."""
    data = _version_step(_report_2_0_to_2_1(_report_1_1_to_2_0(data)), "2.1", "2.2")
    # 2.3 -> 2.4: no confidence spans and no cross-check, the segment confidences stay as they were
    data = _version_step(_report_2_2_to_2_3(data), "2.3", "2.4")
    # 2.4 -> 2.5: no subdivision sections, a re-analysis finds them
    data = _version_step(data, "2.4", "2.5")
    return _report_2_5_to_2_6(data)


def upgrade_beats(data: Any) -> Any:
    """A 1.1 to 2.5 beats file as 2.6."""
    data = _version_step(_beats_2_0_to_2_1(_beats_1_1_to_2_0(data)), "2.1", "2.2")
    # 2.2 -> 2.3: grid_features defaults to empty, the suggestions just can't be checked without the audio
    data = _version_step(data, "2.2", "2.3")
    # 2.3 -> 2.4: cross_check_beats defaults to empty, the cross-check needs the audio again
    data = _version_step(data, "2.3", "2.4")
    # 2.4 -> 2.5: nothing new. a doubled or halved song's positions stay counted per beat, the
    # file doesn't say which stretches were, see docs/decisions.md (real_d)
    data = _version_step(data, "2.4", "2.5")
    # 2.5 -> 2.6: nothing new, the version moves with the report's
    return _version_step(data, "2.5", "2.6")


def _version_step(data: Any, old: str, new: str) -> Any:
    # 2.1 -> 2.2: the report gains offbeat_runs, empty by default, the beats file only moves with it
    if not isinstance(data, dict) or data.get("schema_version") != old:
        return data
    return {**data, "schema_version": new}


def _scale_of(ratio: float) -> float | None:
    for scale in _SCALES:
        if math.isclose(ratio, scale, rel_tol=1e-6):
            return scale
    return None


def _report_2_5_to_2_6(data: Any) -> Any:
    """2.5 -> 2.6: a manual segment whose only edits were x2 or /2 is an auto segment with that notation scale.

    Those were the only way to write a pulse at another octave, so they made the segment manual and a
    re-analysis then left it alone. Only when the log has no split, merge or other change to the whole
    tempo map, since those renumber the segments and an index in an older entry can't be trusted. The
    confidence comes back from the first edit's old value. No auto_result, a re-analysis writes it.
    """
    if not isinstance(data, dict) or data.get("schema_version") != "2.5":
        return data
    out = {**data, "schema_version": "2.6"}
    edits = [e for e in out.get("edits") or [] if isinstance(e, dict)]
    reshaped = any(e.get("field") == "tempo_map" or (e.get("field") == "" and "tempo_map" in (e.get("old") or {})) for e in edits)
    tempo_map = out.get("tempo_map")
    if reshaped or not isinstance(tempo_map, list):
        return out
    upgraded = []
    for i, seg in enumerate(tempo_map):
        upgraded.append(_as_notation(seg, i, edits) if isinstance(seg, dict) and seg.get("source") == "manual" else seg)
    out["tempo_map"] = upgraded
    return out


def _as_notation(seg: dict[str, Any], index: int, edits: list[dict[str, Any]]) -> dict[str, Any]:
    # both log forms count, one entry per field from before milestone 5 and one per change since
    path = f"tempo_map/{index}"
    scale, confidence, touched = 1.0, None, False
    for edit in edits:
        field, old, new = edit.get("field"), edit.get("old"), edit.get("new")
        if field != path and not str(field).startswith(f"{path}/"):
            continue
        touched = True
        if field == f"{path}/source":
            continue
        if field == f"{path}/confidence":
            confidence = old if confidence is None else confidence
            continue
        if field == path:
            if not (isinstance(old, dict) and isinstance(new, dict) and "bpm" in old and set(old) <= {"bpm", "source", "confidence"}):
                return seg
            confidence = old.get("confidence") if confidence is None else confidence
            old, new = old.get("bpm"), new.get("bpm")
        elif field != f"{path}/bpm":
            return seg
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old <= 0:
            return seg
        step = _scale_of(new / old)
        if step is None or step == 1.0:
            return seg
        scale *= step
    final = _scale_of(scale)
    if not touched or final is None or final == 1.0:
        return seg
    return {**seg, "source": "auto", "notation_scale": final, "confidence": confidence}


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
