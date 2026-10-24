import { formatDeltaMs, formatFineMs } from "../format";
import type { SaveState } from "../offset";

interface Props {
  offsetMs: number | null;
  // what the analysis found, before any edit
  autoMs: number | null;
  saveState: SaveState;
  disabled: boolean;
  onNudge: (steps: number) => void;
  onRetry: () => void;
}

function stateText(state: SaveState): string {
  switch (state.kind) {
    case "saved":
      return "saved";
    case "pending":
      return "unsaved";
    case "saving":
      return "saving";
    case "failed":
      return `save failed — ${state.message}`;
  }
}

export function OffsetControl({ offsetMs, autoMs, saveState, disabled, onNudge, onRetry }: Props) {
  const delta = offsetMs !== null && autoMs !== null ? offsetMs - autoMs : null;

  return (
    <div className="offset" aria-labelledby="offset-label">
      <span className="offset__label" id="offset-label">
        beat offset
      </span>
      <output className="offset__value mono" aria-live="polite">
        {offsetMs === null ? "–" : formatFineMs(offsetMs)}
      </output>
      <div className="offset__buttons">
        <button type="button" className="btn btn--step mono" disabled={disabled} onClick={() => onNudge(-1)}>
          −1 ms
        </button>
        <button type="button" className="btn btn--step mono" disabled={disabled} onClick={() => onNudge(1)}>
          +1 ms
        </button>
      </div>
      <p className="offset__meta">
        <span className="mono">{autoMs === null ? "" : `auto ${formatFineMs(autoMs)}`}</span>
        {delta !== null && Math.abs(delta) >= 0.0005 && <span className="mono"> · {formatDeltaMs(delta)}</span>}
      </p>
      <p className="offset__state" data-failed={saveState.kind === "failed"}>
        {disabled ? "" : stateText(saveState)}
        {saveState.kind === "failed" && (
          <button type="button" className="btn btn--link" onClick={onRetry}>
            retry
          </button>
        )}
      </p>
      <p className="offset__hint">← → while the timeline has focus</p>
    </div>
  );
}
