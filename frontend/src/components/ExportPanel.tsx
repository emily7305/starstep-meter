import { useEffect, useState } from "react";
import { ApiError, fetchExport, isAbortError } from "../api";
import {
  compensationPresets,
  DEFAULT_CHOICE,
  type ExportChoice,
  type ExportPreset,
  validCompensation,
} from "../exportOptions";
import type { AudioSource } from "../types/timingReport";

interface Props {
  jobId: string;
  source: AudioSource;
  disabled: boolean;
}

type ExportState = { kind: "idle" } | { kind: "busy" } | { kind: "saved"; filename: string } | { kind: "failed"; message: string };

// the last choice, a player's compensation doesn't change between songs. only a convenience,
// storage can be off or full and then it's just the default again
const STORAGE_KEY = "starstep.export";

function storedChoice(): ExportChoice {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_CHOICE;
    const p = parsed as Partial<ExportChoice>;
    return {
      preset: p.preset === "sonolus" ? "sonolus" : "timing",
      beats: p.beats === true,
      compensationMs: typeof p.compensationMs === "number" && validCompensation(p.compensationMs) ? p.compensationMs : 0,
    };
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

const PRESETS: Array<{ value: ExportPreset; label: string }> = [
  { value: "timing", label: "timing json" },
  { value: "sonolus", label: "sonolus" },
];

export function ExportPanel({ jobId, source, disabled }: Props) {
  const [choice, setChoice] = useState<ExportChoice>(storedChoice);
  const [draft, setDraft] = useState(String(choice.compensationMs));
  const [state, setState] = useState<ExportState>({ kind: "idle" });
  // a new job starts without the last job's message
  useEffect(() => setState({ kind: "idle" }), [jobId]);

  const typed = draft.trim() === "" ? Number.NaN : Number(draft);
  const compensationOk = validCompensation(typed);
  const presets = compensationPresets(source);

  function update(next: ExportChoice) {
    setChoice(next);
    storeChoice(next);
    // the last message was about the other choice
    setState({ kind: "idle" });
  }

  function pickCompensation(ms: number) {
    setDraft(String(ms));
    update({ ...choice, compensationMs: ms });
  }

  async function download() {
    const sent = choice.preset === "sonolus" ? { ...choice, compensationMs: typed } : choice;
    setState({ kind: "busy" });
    try {
      const file = await fetchExport(jobId, sent);
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
      <div className="export__presets" role="group" aria-label="export preset">
        {PRESETS.map((p) => (
          <button
            key={p.value}
            type="button"
            className="btn btn--chip"
            aria-pressed={choice.preset === p.value}
            onClick={() => update({ ...choice, preset: p.value })}
          >
            {p.label}
          </button>
        ))}
      </div>

      {choice.preset === "timing" ? (
        <label className="export__check">
          <input type="checkbox" checked={choice.beats} onChange={(e) => update({ ...choice, beats: e.target.checked })} />
          include beats.json
        </label>
      ) : (
        <div className="export__comp">
          <label className="export__label" htmlFor="export-compensation">
            decoder compensation
          </label>
          <div className="export__comp-row">
            <input
              id="export-compensation"
              className="export__input mono"
              inputMode="decimal"
              aria-invalid={!compensationOk}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                const ms = Number(e.target.value);
                if (e.target.value.trim() !== "" && validCompensation(ms)) update({ ...choice, compensationMs: ms });
              }}
            />
            <span className="export__unit mono">ms</span>
          </div>
          <div className="export__comp-row" role="group" aria-label="compensation presets">
            {presets.map((p) => (
              <button
                key={p.ms}
                type="button"
                className="btn btn--chip mono"
                aria-pressed={compensationOk && typed === p.ms}
                onClick={() => pickCompensation(p.ms)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="export__hint">
            how much later than ffmpeg's decode the player plays the audio, only bgmOffset moves. the padding is
            for a decoder that ignores the gapless info
          </p>
        </div>
      )}

      <div className="export__go">
        <button
          type="button"
          className="btn btn--outline"
          disabled={disabled || state.kind === "busy" || (choice.preset === "sonolus" && !compensationOk)}
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
