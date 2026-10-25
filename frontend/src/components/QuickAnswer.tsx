import { useMemo, useState } from "react";
import { formatOffset } from "../chartSetup";
import {
  bpmLabel,
  changesLine,
  HARD_TO_READ,
  HELP,
  originalLabel,
  quickAnswer,
  quickText,
  setupFor,
  WAV_LABEL,
} from "../quickAnswer";
import type { ChartStart } from "../tempoMap";
import type { TimingReport } from "../types/timingReport";
import { copyToClipboard } from "./ChartSetup";

interface Props {
  report: TimingReport;
  start: ChartStart;
}

type HelpKey = keyof typeof HELP;

const MORE_DECIMALS = 4;

function HelpButton({ topic, open, onToggle }: { topic: HelpKey; open: boolean; onToggle: (topic: HelpKey) => void }) {
  return (
    <button
      type="button"
      className="quick__help-btn"
      title={HELP[topic]}
      aria-label={`what is this: ${HELP[topic]}`}
      aria-expanded={open}
      onClick={() => onToggle(topic)}
    >
      ?
    </button>
  );
}

// the basics first, in plain words: what a chart editor needs typed in. everything technical
// stays in the panels under it
export function QuickAnswer({ report, start }: Props) {
  const answer = useMemo(() => quickAnswer(report, setupFor(report, start)), [report, start]);
  const [decimals, setDecimals] = useState(2);
  const [help, setHelp] = useState<HelpKey | null>(null);
  const [copyState, setCopyState] = useState<string | null>(null);
  if (answer === null) return null;
  const changes = changesLine(answer);
  const toggle = (topic: HelpKey) => setHelp((open) => (open === topic ? null : topic));

  return (
    <section className="quick" aria-labelledby="quick-label">
      <div className="quick__head">
        <h2 className="quick__title" id="quick-label">
          for your chart
        </h2>
        <button
          type="button"
          className="btn btn--chip"
          aria-pressed={decimals > 2}
          onClick={() => setDecimals((d) => (d > 2 ? 2 : MORE_DECIMALS))}
        >
          more decimals
        </button>
        <button
          type="button"
          className="btn btn--outline"
          onClick={() => void copyToClipboard(quickText(answer, decimals)).then(setCopyState)}
        >
          copy
        </button>
        {copyState !== null && <span className="quick__copied">{copyState}</span>}
      </div>

      <dl className="quick__values">
        <div className="quick__item">
          <dt>
            {bpmLabel(answer)} <HelpButton topic="bpm" open={help === "bpm"} onToggle={toggle} />
          </dt>
          <dd className="quick__big mono">{answer.bpm.toFixed(decimals)}</dd>
        </div>
        <div className="quick__item">
          <dt>
            offset <HelpButton topic="offset" open={help === "offset"} onToggle={toggle} />
          </dt>
          <dd>
            <span className="quick__which">{WAV_LABEL}</span>
            <span className="quick__big mono">{formatOffset(answer.wavOffsetMs)}</span>
          </dd>
          {answer.originalOffsetMs !== null && (
            <dd>
              <span className="quick__which">{originalLabel(answer)}</span>
              <span className="quick__big mono">{formatOffset(answer.originalOffsetMs)}</span>
            </dd>
          )}
        </div>
        <div className="quick__item">
          <dt>
            time signature <HelpButton topic="signature" open={help === "signature"} onToggle={toggle} />
          </dt>
          <dd className="quick__big mono">
            {answer.numerator}/{answer.denominator}
          </dd>
        </div>
      </dl>

      {help !== null && <p className="quick__explain">{HELP[help]}</p>}
      {changes !== null && (
        <p className="quick__changes">
          {changes}. <a href="#chart-setup">see every change</a>
        </p>
      )}
      {answer.hardToRead && <p className="quick__warn">{HARD_TO_READ}</p>}
    </section>
  );
}
