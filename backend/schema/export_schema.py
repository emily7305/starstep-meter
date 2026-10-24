"""Write shared/schema/timing_report.schema.json from the pydantic model.

Usage: python -m backend.schema.export_schema [--check]

--check exits 1 if the committed file doesn't match the model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.schema.models import TimingReport

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "shared" / "schema" / "timing_report.schema.json"


def render_schema() -> str:
    schema = TimingReport.model_json_schema(mode="serialization")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "timing_report.schema.json",
        **schema,
    }
    # sorted keys + trailing newline so the file diffs cleanly on every os
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed schema is stale")
    args = parser.parse_args(argv)

    rendered = render_schema()
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != rendered:
            print(f"{SCHEMA_PATH.relative_to(REPO_ROOT)} is out of date, run python -m backend.schema.export_schema")
            return 1
        print("schema up to date")
        return 0

    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
