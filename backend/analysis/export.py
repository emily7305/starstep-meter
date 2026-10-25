"""Export files from a timing report: the plain timing json, or the Sonolus preset.

Usage:
    python -m backend.analysis.export report.json [--beats beats.json]
    python -m backend.analysis.export report.json --sonolus [--decoder-compensation-ms MS | --decoder-padding]

Timing data only, never audio. Both are checked against shared/schema before they're returned.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.sonolus import decoder_padding_ms, level_entities, sonolus_timing
from backend.schema.export_models import SonolusExport, TimingExport
from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport
from backend.schema.validate import validate

TIMING_SCHEMA = "timing_export.schema.json"
SONOLUS_SCHEMA = "sonolus_export.schema.json"


class ExportError(ValueError):
    pass


def timing_export(report: TimingReport, beats: BeatsFile | None, now: datetime) -> dict:
    """The report as it is, with the beats file when one is given, checked against the schema."""
    if beats is not None and beats.sha256 != report.source.sha256:
        raise ExportError("the beats file is from another source file than the report")
    doc = TimingExport(exported_at=now, report=report, beats=beats).model_dump(
        mode="json", exclude={"beats"} if beats is None else set()
    )
    validate(doc, TIMING_SCHEMA)
    return doc


def sonolus_export(report: TimingReport, now: datetime, decoder_compensation_ms: float = 0.0) -> dict:
    """bgmOffset, the bpm changes and the time signatures for a Sonolus level, checked against the schema."""
    timing = sonolus_timing(report.tempo_map, report.meter_map, decoder_compensation_ms)
    doc = SonolusExport.model_validate(
        {
            "exported_at": now,
            "filename": report.source.filename,
            "sha256": report.source.sha256,
            "decoder_compensation_ms": decoder_compensation_ms,
            "first_downbeat_beat": timing.first_downbeat_beat,
            "level_data": {"bgmOffset": timing.bgm_offset_s, "entities": level_entities(timing)},
            "bpm_changes": [{"beat": c.beat, "bpm": c.bpm, "time_ms": c.time_ms} for c in timing.bpm_changes],
            "time_signatures": [
                {"beat": t.beat, "numerator": t.numerator, "denominator": t.denominator} for t in timing.time_signatures
            ],
        }
    ).model_dump(mode="json")
    validate(doc, SONOLUS_SCHEMA)
    return doc


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="a report.json from data/jobs/<job id>/")
    parser.add_argument("--beats", type=Path, help="also put this beats.json in the plain export")
    parser.add_argument("--sonolus", action="store_true", help="the Sonolus preset instead of the plain export")
    comp = parser.add_mutually_exclusive_group()
    comp.add_argument("--decoder-compensation-ms", type=float, default=0.0, help="ms the player plays the audio late")
    comp.add_argument("--decoder-padding", action="store_true", help="compensate by the source's decoder padding")
    args = parser.parse_args(argv)

    try:
        report = TimingReport.model_validate(upgrade_report(_read(args.report)))
        now = datetime.now(timezone.utc)
        if args.sonolus:
            if args.beats is not None:
                raise ExportError("--beats only goes with the plain export")
            ms = args.decoder_compensation_ms
            if args.decoder_padding:
                ms = round(decoder_padding_ms(report.source.decoder_padding_samples, report.source.sample_rate), 3)
            doc = sonolus_export(report, now, ms)
        else:
            if args.decoder_padding or args.decoder_compensation_ms:
                raise ExportError("decoder compensation only goes with --sonolus")
            beats = BeatsFile.model_validate(upgrade_beats(_read(args.beats))) if args.beats else None
            doc = timing_export(report, beats, now)
    except (OSError, ValueError) as exc:
        # pydantic's ValidationError and SchemaMismatch are ValueErrors too
        print(f"export failed: {exc}", file=sys.stderr)
        return 1
    # ascii escapes, a japanese title would break a cp1252 console on windows
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
