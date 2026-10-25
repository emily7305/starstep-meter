"""Check a json document against one of the committed schemas in shared/schema/.

The exports are checked here before they go out, against the files on disk rather than
the pydantic models, so a stale schema file shows up as a failed export and not as a
consumer that can't read what it was given.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "shared" / "schema"


class SchemaMismatch(ValueError):
    pass


@cache
def _validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate(document: object, schema_name: str) -> None:
    """Raises SchemaMismatch naming the first place the document doesn't fit."""
    errors = sorted(_validator(schema_name).iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "the top level"
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        raise SchemaMismatch(f"doesn't match {schema_name} at {where}: {first.message}{more}")
