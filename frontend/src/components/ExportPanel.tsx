import { useEffect, useState } from "react";
import { ApiError, fetchExport, isAbortError } from "../api";
import { DEFAULT_CHOICE, type ExportChoice } from "../exportOptions";

interface Props {
  jobId: string;
  disabled: boolean;
}

type ExportState = { kind: "idle" } | { kind: "busy" } | { kind: "saved"; filename: string } | { kind: "failed"; message: string };

// the last choice. only a convenience, storage can be off or full and then it's just the default
// again. an older entry can have more keys, only beats is read
const STORAGE_KEY = "starstep.export";

function storedChoice(): ExportChoice {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_CHOICE;
    return { beats: (parsed as Partial<ExportChoice>).beats === true };
  } catch {
    return DEFAULT_CHOICE;
  }
}

function storeChoice(choice: ExportChoice): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(choice));
  } catch {
    // nothing to do, it just won't be remembered
  }
}

function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // the click has started the download by the next tick
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ExportPanel({ jobId, disabled }: Props) {
  const [choice, setChoice] = useState<ExportChoice>(storedChoice);
  const [state, setState] = useState<ExportState>({ kind: "idle" });
  // a new job starts without the last job's message
  useEffect(() => setState({ kind: "idle" }), [jobId]);

  function update(next: ExportChoice) {
    setChoice(next);
    storeChoice(next);
    // the last message was about the other choice
    setState({ kind: "idle" });
  }

  async function download() {
    setState({ kind: "busy" });
    try {
      const file = await fetchExport(jobId, choice);
      save(file.blob, file.filename);
      setState({ kind: "saved", filename: file.filename });
    } catch (err) {
      if (isAbortError(err)) return;
      const message = err instanceof ApiError && err.offline ? "backend offline" : err instanceof Error ? err.message : "unknown error";
      setState({ kind: "failed", message });
    }
  }

  return (
    <div className="export" role="group" aria-labelledby="export-label">
      <h2 className="section-label section-label--spaced" id="export-label">
        export
      </h2>
      <label className="export__check" title="put the beats file in the export too, timing data only">
        <input
          type="checkbox"
          checked={choice.beats}
          title="put the beats file in the export too, timing data only"
          onChange={(e) => update({ beats: e.target.checked })}
        />
        include beats.json
      </label>

      <div className="export__go">
        <button
          type="button"
          className="btn btn--outline"
          disabled={disabled || state.kind === "busy"}
          title="download the report as a json file, with the beats file in it when the box above is ticked"
          onClick={() => void download()}
        >
          export json
        </button>
        <span className="export__state" data-failed={state.kind === "failed"} aria-live="polite">
          {state.kind === "busy" && "exporting"}
          {state.kind === "saved" && (
            <>
              saved <span className="mono">{state.filename}</span>
            </>
          )}
          {state.kind === "failed" && `export failed — ${state.message}`}
        </span>
      </div>
      <p className="export__hint">timing data only, never audio</p>
    </div>
  );
}
