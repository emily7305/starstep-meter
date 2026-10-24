import { formatBpm, formatMs } from "../format";
import type { TempoEditOp } from "../types/api";
import type { NotationSuggestion } from "../types/timingReport";

interface Props {
  suggestions: NotationSuggestion[];
  // index into suggestions
  selected: number | null;
  disabled: boolean;
  onSelect: (index: number) => void;
  onEdit: (op: TempoEditOp) => void;
}

export function suggestionKindText(kind: NotationSuggestion["kind"]): string {
  switch (kind) {
    case "half":
      return "half time";
    case "double":
      return "double time";
    case "fold":
      return "fold into neighbour";
  }
}

// the decided ones stay in the report as history, one line is all they get on screen
export function decidedText(suggestions: NotationSuggestion[]): string {
  const applied = suggestions.filter((s) => s.status === "applied").length;
  const dismissed = suggestions.filter((s) => s.status === "dismissed").length;
  const parts: string[] = [];
  if (applied > 0) parts.push(`${applied} applied`);
  if (dismissed > 0) parts.push(`${dismissed} dismissed`);
  return parts.join(", ");
}

export function SuggestionList(props: Props) {
  const { suggestions, selected, disabled, onSelect, onEdit } = props;
  // the indices stay those of the full array, that's what the edits and the timeline use
  const open = suggestions.flatMap((suggestion, i) => (suggestion.status === "open" ? [{ suggestion, i }] : []));
  const decided = decidedText(suggestions);

  return (
    <section className="suggestions" aria-labelledby="suggestions-label">
      <p className="suggestions__label" id="suggestions-label">
        notation suggestions
      </p>
      <p className="suggestions__note">the analysis never applies these</p>

      {open.length > 0 && (
        <ul className="suggestions__list">
          {open.map(({ suggestion, i }) => (
            <li key={i} className="suggestions__item" data-selected={i === selected}>
              <button
                type="button"
                className="suggestions__go"
                disabled={disabled}
                aria-current={i === selected ? "true" : undefined}
                onClick={() => onSelect(i)}
              >
                <span className="suggestions__kind">{suggestionKindText(suggestion.kind)}</span>
                <span className="suggestions__range mono">
                  {formatMs(suggestion.start_ms)} → {formatMs(suggestion.end_ms)}
                </span>
                <span className="suggestions__bpm mono">
                  {formatBpm(suggestion.suggested_bpm)}
                  <span className="suggestions__from"> from {formatBpm(suggestion.grid_bpm)}</span>
                </span>
                <span className="suggestions__score mono" title="how clear it is, 1 is as clear as it gets">
                  {suggestion.score.toFixed(2)}
                </span>
              </button>
              <div className="suggestions__actions">
                <button
                  type="button"
                  className="btn btn--step"
                  disabled={disabled}
                  title="split at both ends and set the span to the suggested bpm, every grid line stays where it is"
                  onClick={() => onEdit({ op: "apply_suggestion", suggestion: i })}
                >
                  apply
                </button>
                <button
                  type="button"
                  className="btn btn--step"
                  disabled={disabled}
                  onClick={() => onEdit({ op: "dismiss_suggestion", suggestion: i })}
                >
                  dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {decided !== "" && <p className="suggestions__decided">{decided}</p>}
      {open.length === 0 && decided === "" && <p className="suggestions__empty">no suggestions</p>}
    </section>
  );
}
