// how one entry of the edit log reads in the report column. one manual change is one entry:
// a single value at its own path, or several as objects keyed by their path under the field
// ("" being the report itself), see backend/api/tempo_patch.py

import { formatFineMs } from "./format";
import type { Edit } from "./types/timingReport";

export interface EditChange {
  path: string;
  old: string;
  new: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function valueText(path: string, value: unknown): string {
  if (value === null) return "–";
  // split, merge and match log the whole map
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "segment" : "segments"}`;
  if (typeof value === "number") {
    if (path.endsWith("/bpm")) return `${value} bpm`;
    if (path.endsWith("confidence")) return value.toFixed(3);
    if (path.endsWith("numerator") || path.endsWith("denominator")) return String(value);
    return formatFineMs(value);
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

// both sides objects is an entry of several values, anything else is one value
export function editChanges(edit: Edit): EditChange[] {
  const { old, new: next } = edit;
  if (isRecord(old) && isRecord(next)) {
    return Object.keys(next).map((key) => {
      const path = edit.field === "" ? key : `${edit.field}/${key}`;
      return { path: key, old: valueText(path, old[key]), new: valueText(path, next[key]) };
    });
  }
  return [{ path: "", old: valueText(edit.field, old), new: valueText(edit.field, next) }];
}

export function editLabel(edit: Edit): string {
  if (edit.field !== "") return edit.field;
  // an entry at the report itself, say what it touched
  return isRecord(edit.new) ? Object.keys(edit.new).join(" + ") : "report";
}
