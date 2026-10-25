"""Export the timing json from a timing report.

Usage:
    python -m backend.analysis.export report.json [--beats beats.json]

Timing data only, never audio. Checked against shared/schema before it's returned.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.schema.export_models import TimingExport
from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport
from backend.schema.validate import validate

TIMING_SCHEMA = "timing_export.schema.json"


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


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="a report.json from data/jobs/<job id>/")
    parser.add_argument("--beats", type=Path, help="also put this beats.json in the plain export")
    args = parser.parse_args(argv)

    try:
        report = TimingReport.model_validate(upgrade_report(_read(args.report)))
        now = datetime.now(timezone.utc)
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
