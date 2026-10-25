import { formatBpm, formatMs } from "../format";
import { divisionAt, divisionText, feelKindText } from "../subdivisions";
import type { TempoEditOp } from "../types/api";
import type { NotationSuggestion, SubdivisionSection } from "../types/timingReport";

interface Props {
  suggestions: NotationSuggestion[];
  // index into suggestions
  selected: number | null;
  // swing and gallop, listed here too but never applied, there's nothing in the map to change
  feels: SubdivisionSection[];
  // the bpm each one's segment has now
  feelBpm: number[];
  // for a downbeat shift, how far into the bar on screen the tracker's bars restart, by suggestion index
  shiftBeats: (number | null)[];
  selectedFeel: number | null;
  disabled: boolean;
  onSelect: (index: number) => void;
  onSelectFeel: (index: number) => void;
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
    case "shift":
      return "downbeat may shift here";
  }
}

// what the bpm column says for a downbeat shift, the bpm doesn't change
export function shiftText(beats: number | null): string {
  if (beats === null || beats === 0) return "bars restart here";
  return `bars restart ${beats} ${beats === 1 ? "beat" : "beats"} into the bar`;
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
  const { suggestions, selected, feels, feelBpm, shiftBeats, selectedFeel, disabled, onSelect, onSelectFeel, onEdit } = props;
  // the indices stay those of the full array, that's what the edits and the timeline use
  const open = suggestions.flatMap((suggestion, i) => (suggestion.status === "open" ? [{ suggestion, i }] : []));
  const decided = decidedText(suggestions);

  return (
    <section className="suggestions" aria-labelledby="suggestions-label">
      <p className="suggestions__label" id="suggestions-label">
        notation suggestions
      </p>
      <p className="suggestions__note">the analysis never applies these, a row jumps there</p>

      {open.length > 0 && (
        <ul className="suggestions__list">
          {open.map(({ suggestion, i }) => (
            <li key={i} className="suggestions__item" data-selected={i === selected}>
              <button
                type="button"
                className="suggestions__go"
                disabled={disabled}
                aria-current={i === selected ? "true" : undefined}
                title="jump the timeline and the zoomed view to where it starts"
                onClick={() => onSelect(i)}
              >
                <span className="suggestions__kind">{suggestionKindText(suggestion.kind)}</span>
                <span className="suggestions__range mono">
                  {formatMs(suggestion.start_ms)} → {formatMs(suggestion.end_ms)}
                </span>
                {suggestion.kind === "shift" ? (
                  <span
                    className="suggestions__bpm"
                    title="the tracker heard one short bar here and its bars carry on from it, apply restarts the bars on this beat"
                  >
                    {shiftText(shiftBeats[i] ?? null)}
                  </span>
                ) : (
                  <span className="suggestions__bpm mono">
                    {formatBpm(suggestion.suggested_bpm)}
                    <span className="suggestions__from"> from {formatBpm(suggestion.grid_bpm)}</span>
                  </span>
                )}
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
                  title="keep the grid as it is here, the suggestion is logged as dismissed"
                  onClick={() => onEdit({ op: "dismiss_suggestion", suggestion: i })}
                >
                  dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {feels.length > 0 && (
        <ul className="suggestions__list suggestions__list--feel" aria-label="swing and gallop">
          {feels.map((section, i) => (
            <li key={`${section.start_ms}-${section.kind}`} className="suggestions__item" data-selected={i === selectedFeel}>
              <button
                type="button"
                className="suggestions__go"
                aria-current={i === selectedFeel ? "true" : undefined}
                title="the notes between the beats are uneven here, set the editor's grid to this division for them"
                onClick={() => onSelectFeel(i)}
              >
                <span className="suggestions__kind">{feelKindText(section)}</span>
                <span className="suggestions__range mono">
                  {formatMs(section.start_ms)} → {formatMs(section.end_ms)}
                </span>
                <span className="suggestions__bpm mono">
                  {divisionText(divisionAt(section.division, section.grid_bpm, feelBpm[i] ?? section.grid_bpm))}
                </span>
                <span className="suggestions__score mono" title="how clear it is, 1 is as clear as it gets">
                  {section.score.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {decided !== "" && <p className="suggestions__decided">{decided}</p>}
      {open.length === 0 && feels.length === 0 && decided === "" && (
        <p className="suggestions__empty">none for this song, half or double time, folds, swing and gallop show up here</p>
      )}
    </section>
  );
}
