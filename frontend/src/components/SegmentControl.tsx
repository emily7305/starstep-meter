import { type FormEvent, useEffect, useState } from "react";
import { formatFineMs } from "../format";
import { type SaveState, validBpm } from "../tempoEdits";
import type { TempoEditOp } from "../types/api";
import type { TempoSegment } from "../types/timingReport";

interface Props {
  segment: TempoSegment;
  index: number;
  count: number;
  // what's on screen, a nudged anchor before the server has it
  anchorMs: number;
  // the tracked beat in the zoomed view, where anchor here and split here act
  beatMs: number | null;
  saveState: SaveState;
  disabled: boolean;
  onNudge: (steps: number) => void;
  onEdit: (op: TempoEditOp) => void;
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

// four decimals, x2 and /2 of a fitted bpm shouldn't look rounded away
function bpmText(bpm: number): string {
  return `${bpm.toFixed(4)} bpm`;
}

export function SegmentControl(props: Props) {
  const { segment, index, count, anchorMs, beatMs, saveState, disabled, onNudge, onEdit, onRetry } = props;
  const [bpmDraft, setBpmDraft] = useState(String(segment.bpm));
  useEffect(() => setBpmDraft(String(segment.bpm)), [segment.bpm, index]);

  const typed = Number(bpmDraft.trim());
  const typedOk = bpmDraft.trim() !== "" && validBpm(typed);
  const insideSegment = beatMs !== null && beatMs > segment.start_ms && beatMs < segment.end_ms;

  function submitBpm(event: FormEvent) {
    event.preventDefault();
    if (typedOk && typed !== segment.bpm) onEdit({ op: "set_bpm", segment: index, bpm: typed });
  }

  return (
    <div className="segment" aria-labelledby="segment-label">
      <p className="segment__head">
        <span className="segment__label" id="segment-label">
          segment {index + 1} of {count}
        </span>
        <span className="segment__source" data-manual={segment.source === "manual"}>
          {segment.source}
        </span>
      </p>
      <p className="segment__range mono">
        {formatFineMs(segment.start_ms)} → {formatFineMs(segment.end_ms)}
      </p>

      <span className="segment__sub">bpm</span>
      <output className="segment__value mono" aria-live="polite">
        {bpmText(segment.bpm)}
      </output>
      <div className="segment__buttons">
        <button
          type="button"
          className="btn btn--step mono"
          disabled={disabled || !validBpm(segment.bpm / 2)}
          onClick={() => onEdit({ op: "set_bpm", segment: index, bpm: segment.bpm / 2 })}
          aria-label="half the bpm, the grid is rebuilt from the anchor"
        >
          ÷2
        </button>
        <button
          type="button"
          className="btn btn--step mono"
          disabled={disabled || !validBpm(segment.bpm * 2)}
          onClick={() => onEdit({ op: "set_bpm", segment: index, bpm: segment.bpm * 2 })}
          aria-label="double the bpm, the grid is rebuilt from the anchor"
        >
          ×2
        </button>
      </div>
      <form className="segment__set" onSubmit={submitBpm}>
        <input
          className="segment__input mono"
          inputMode="decimal"
          aria-label="bpm for this segment"
          aria-invalid={!typedOk}
          value={bpmDraft}
          disabled={disabled}
          onChange={(event) => setBpmDraft(event.target.value)}
          // arrow keys here edit the text, not the anchor
          onKeyDown={(event) => event.stopPropagation()}
        />
        <button type="submit" className="btn btn--step" disabled={disabled || !typedOk || typed === segment.bpm}>
          set bpm
        </button>
      </form>

      <span className="segment__sub">anchor</span>
      <output className="segment__value mono" aria-live="polite">
        {formatFineMs(anchorMs)}
      </output>
      <div className="segment__buttons">
        <button type="button" className="btn btn--step mono" disabled={disabled} onClick={() => onNudge(-1)}>
          −1 ms
        </button>
        <button type="button" className="btn btn--step mono" disabled={disabled} onClick={() => onNudge(1)}>
          +1 ms
        </button>
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || beatMs === null}
          title="rebuild the grid from the tracked beat in the zoomed view"
          onClick={() => beatMs !== null && onEdit({ op: "set_anchor", segment: index, anchor_ms: beatMs })}
        >
          anchor here
        </button>
      </div>

      <span className="segment__sub">segments</span>
      <div className="segment__buttons">
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || !insideSegment}
          title="split this segment at the tracked beat in the zoomed view"
          onClick={() => beatMs !== null && onEdit({ op: "split", at_ms: beatMs })}
        >
          split here
        </button>
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || index === 0}
          onClick={() => onEdit({ op: "merge", segment: index - 1 })}
        >
          merge ←
        </button>
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || index >= count - 1}
          onClick={() => onEdit({ op: "merge", segment: index })}
        >
          merge →
        </button>
      </div>

      <p className="segment__state" data-failed={saveState.kind === "failed"}>
        {disabled ? "" : stateText(saveState)}
        {saveState.kind === "failed" && (
          <button type="button" className="btn btn--link" onClick={onRetry}>
            retry
          </button>
        )}
      </p>
      <p className="segment__hint">← → move the anchor while the timeline has focus</p>
    </div>
  );
}
