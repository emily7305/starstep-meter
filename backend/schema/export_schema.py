"""Write the json schemas in shared/schema/ from the pydantic models.

Usage: python -m backend.schema.export_schema [--check]

--check exits 1 if a committed file doesn't match its model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from backend.schema.export_models import TimingExport
from backend.schema.models import BeatsFile, TimingReport

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "shared" / "schema"
SCHEMA_PATH = SCHEMA_DIR / "timing_report.schema.json"
BEATS_SCHEMA_PATH = SCHEMA_DIR / "beats.schema.json"
TIMING_EXPORT_SCHEMA_PATH = SCHEMA_DIR / "timing_export.schema.json"

SCHEMAS: dict[Path, type[BaseModel]] = {
    SCHEMA_PATH: TimingReport,
    BEATS_SCHEMA_PATH: BeatsFile,
    TIMING_EXPORT_SCHEMA_PATH: TimingExport,
}


def render_schema(model: type[BaseModel] = TimingReport) -> str:
    path = next(p for p, m in SCHEMAS.items() if m is model)
    schema = model.model_json_schema(mode="serialization")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": path.name,
        **schema,
    }
    # sorted keys + trailing newline so the file diffs cleanly on every os
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed schema is stale")
    args = parser.parse_args(argv)

    stale = False
    for path, model in SCHEMAS.items():
        rendered = render_schema(model)
        shown = path.relative_to(REPO_ROOT)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                print(f"{shown} is out of date, run python -m backend.schema.export_schema")
                stale = True
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {shown}")

    if args.check:
        if stale:
            return 1
        print("schema up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
