import { type FormEvent, useEffect, useState } from "react";
import { formatFineMs } from "../format";
import type { TempoEditOp } from "../types/api";
import type { MeterSegment } from "../types/timingReport";

interface Props {
  meter: MeterSegment;
  index: number;
  count: number;
  // the tracked beat (or nearest grid line) in the zoomed view, where "split meter here" acts
  splitAtMs: number | null;
  disabled: boolean;
  onEdit: (op: TempoEditOp) => void;
}

const DENOMINATORS = [1, 2, 4, 8, 16, 32];
// the schema stops at 32 beats per bar
const MAX_NUMERATOR = 32;

// digits only, so "1e1" and "0x10" don't count as numbers
function parseNumerator(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value >= 1 && value <= MAX_NUMERATOR ? value : null;
}

export function MeterControl(props: Props) {
  const { meter, index, count, splitAtMs, disabled, onEdit } = props;
  const [numeratorDraft, setNumeratorDraft] = useState(String(meter.numerator));
  const [denominatorDraft, setDenominatorDraft] = useState(meter.denominator);
  useEffect(() => {
    setNumeratorDraft(String(meter.numerator));
    setDenominatorDraft(meter.denominator);
  }, [meter.numerator, meter.denominator, meter.start_ms, index]);

  const typed = parseNumerator(numeratorDraft);
  const unchanged = typed === meter.numerator && denominatorDraft === meter.denominator;
  // the schema also allows 64, keep a segment that has it from showing another option
  const denominators = DENOMINATORS.includes(meter.denominator) ? DENOMINATORS : [...DENOMINATORS, meter.denominator];
  const insideMeter = splitAtMs !== null && splitAtMs > meter.start_ms && splitAtMs < meter.end_ms;

  function submitMeter(event: FormEvent) {
    event.preventDefault();
    if (typed !== null && !unchanged) {
      onEdit({ op: "set_meter", segment: index, numerator: typed, denominator: denominatorDraft });
    }
  }

  return (
    <div className="meter" role="group" aria-labelledby="meter-label">
      <p className="meter__head">
        <span className="meter__label" id="meter-label">
          meter {index + 1} of {count}
        </span>
        <span className="meter__source" data-manual={meter.source === "manual"}>
          {meter.source}
        </span>
      </p>
      <p className="meter__range mono">
        {formatFineMs(meter.start_ms)} → {formatFineMs(meter.end_ms)}
      </p>

      <p className="meter__now">
        <output className="meter__value mono" aria-live="polite">
          {meter.numerator}/{meter.denominator}
        </output>
        {meter.confidence !== null && <span className="meter__confidence mono">confidence {meter.confidence.toFixed(2)}</span>}
      </p>
      <form className="meter__set" onSubmit={submitMeter}>
        <input
          className="meter__input mono"
          inputMode="numeric"
          aria-label="beats per bar"
          title="beats per bar, a whole number from 1 to 32, enter does the same as set meter"
          aria-invalid={typed === null}
          value={numeratorDraft}
          disabled={disabled}
          onChange={(event) => setNumeratorDraft(event.target.value)}
          // arrow keys here edit the text, not the anchor
          onKeyDown={(event) => event.stopPropagation()}
        />
        <span className="meter__slash mono" aria-hidden="true">
          /
        </span>
        <select
          className="meter__select mono"
          aria-label="note value of a beat"
          title="the note value that counts as one beat, 4 is a quarter note"
          value={denominatorDraft}
          disabled={disabled}
          onChange={(event) => setDenominatorDraft(Number(event.target.value))}
          // arrow keys here pick an option, not nudge the anchor
          onKeyDown={(event) => event.stopPropagation()}
        >
          {denominators.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="btn btn--step"
          disabled={disabled || typed === null || unchanged}
          title="set this time signature for the meter segment under the zoomed view"
        >
          set meter
        </button>
      </form>

      <div className="meter__buttons">
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || !insideMeter}
          title="start a new meter at the beat in the zoomed view, bars restart there"
          onClick={() => splitAtMs !== null && onEdit({ op: "split_meter", at_ms: splitAtMs })}
        >
          split meter here
        </button>
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || index === 0}
          title="merge with the meter segment before, the pair becomes one manual meter segment"
          onClick={() => onEdit({ op: "merge_meter", segment: index - 1 })}
        >
          merge ←
        </button>
        <button
          type="button"
          className="btn btn--step"
          disabled={disabled || index >= count - 1}
          title="merge with the meter segment after, the pair becomes one manual meter segment"
          onClick={() => onEdit({ op: "merge_meter", segment: index })}
        >
          merge →
        </button>
      </div>

      <p className="meter__hint">a bar is numerator × 4 / denominator beats of the grid</p>
    </div>
  );
}
