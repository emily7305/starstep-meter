"""Turn a Sonolus export into level data for a click-track test level.

Usage: python scripts/make_sonolus_test_level.py song.sonolus.json level-data.json.gz [--beats 64]
       [--archetype NormalTapNote] [--data lane=0] [--data size=1.5] [--no-gzip]

One tap note on every beat of the grid from the first downbeat, with the export's
bgmOffset and bpm changes. With the click track as the bgm and note sounds on, every
note should land on a click. The archetype and its extra data depend on the engine,
the defaults are the pjsekai engine's (NormalTapNote with lane and size, the way its
usc converter writes one). Sonolus wants level data gzipped, so it is unless --no-gzip.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

# beats this close to a whole number of the grid are on it, float noise only
ON_BEAT = 1e-6


def note_beats(bpm_changes: list[dict], first_downbeat_beat: float, count: int) -> list[float]:
    """Every grid beat from the first downbeat on, each tempo's grid counted from its own change."""
    out: list[float] = []
    for i, change in enumerate(bpm_changes):
        start = change["beat"]
        stop = bpm_changes[i + 1]["beat"] if i + 1 < len(bpm_changes) else math.inf
        k = max(0, math.ceil(first_downbeat_beat - start - ON_BEAT)) if i == 0 else 0
        while len(out) < count and start + k < stop - ON_BEAT:
            out.append(round(start + k, 6))
            k += 1
    return out


def test_level_data(export: dict, count: int, archetype: str, extra: dict[str, float]) -> dict:
    if export.get("kind") != "sonolus":
        raise ValueError("that's not a sonolus export, export with the sonolus preset")
    level = export["level_data"]
    notes = [
        {
            "archetype": archetype,
            "data": [{"name": "#BEAT", "value": beat}, *({"name": k, "value": v} for k, v in extra.items())],
        }
        for beat in note_beats(export["bpm_changes"], export["first_downbeat_beat"], count)
    ]
    entities = [{"archetype": "Initialization", "data": []}, {"archetype": "Stage", "data": []}, *level["entities"], *notes]
    return {"bgmOffset": level["bgmOffset"], "entities": entities}


def _data(text: str) -> tuple[str, float]:
    name, _, value = text.partition("=")
    try:
        return name, float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected NAME=NUMBER like lane=0, got {text!r}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="a .sonolus.json from the export button or the export cli")
    parser.add_argument("out", type=Path, help="where to write the level data")
    parser.add_argument("--beats", type=int, default=64, help="how many notes, one per beat")
    parser.add_argument("--archetype", default="NormalTapNote", help="the engine's tap note archetype")
    parser.add_argument("--data", type=_data, action="append", help="extra note data, NAME=NUMBER, repeatable")
    parser.add_argument("--no-gzip", action="store_true", help="plain json, for reading it")
    args = parser.parse_args(argv)
    extra = dict(args.data) if args.data else {"lane": 0.0, "size": 1.5}

    try:
        export = json.loads(args.export.read_text(encoding="utf-8"))
        level = test_level_data(export, args.beats, args.archetype, extra)
    except (OSError, ValueError, KeyError) as exc:
        print(f"can't make the level: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(level, separators=(",", ":")).encode("utf-8")
    args.out.write_bytes(text if args.no_gzip else gzip.compress(text))
    notes = len(level["entities"]) - 2 - len(export["level_data"]["entities"])
    print(f"wrote {args.out}: bgmOffset {level['bgmOffset']}, {notes} notes from beat {export['first_downbeat_beat']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
