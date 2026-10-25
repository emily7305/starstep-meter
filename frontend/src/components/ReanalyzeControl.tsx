import { useState } from "react";
import type { ReanalyzeMode } from "../api";

interface Props {
  disabled: boolean;
  onReanalyze: (mode: ReanalyzeMode) => void;
}

type Step = "closed" | "choose" | "confirm";

// re-analyze asks first whether the manual edits stay. starting fresh drops them, so it asks twice
export function ReanalyzeControl({ disabled, onReanalyze }: Props) {
  const [step, setStep] = useState<Step>("closed");

  const run = (mode: ReanalyzeMode) => {
    setStep("closed");
    onReanalyze(mode);
  };

  if (step === "closed") {
    return (
      <div className="reanalyze">
        <button
          type="button"
          className="btn btn--outline"
          disabled={disabled}
          title="run every stage again on the stored upload, it asks what happens to the manual edits"
          onClick={() => setStep("choose")}
        >
          re-analyze
        </button>
      </div>
    );
  }

  if (step === "choose") {
    return (
      <div className="reanalyze reanalyze--open" role="group" aria-label="re-analyze">
        <button
          type="button"
          className="btn btn--primary"
          disabled={disabled}
          autoFocus
          title="manual segments, x2 and /2, decided suggestions and the edit log stay, the rest is analyzed again"
          onClick={() => run("keep")}
        >
          keep my edits
        </button>
        <button
          type="button"
          className="btn btn--outline"
          disabled={disabled}
          title="analyze it as if it were new, every manual edit goes. the edit log keeps what they were"
          onClick={() => setStep("confirm")}
        >
          start fresh
        </button>
        <button type="button" className="btn btn--link" title="don't re-analyze" onClick={() => setStep("closed")}>
          cancel
        </button>
      </div>
    );
  }

  return (
    <div className="reanalyze reanalyze--open" role="alertdialog" aria-label="start fresh">
      <p className="reanalyze__ask">drop every manual edit of this song and analyze it again? the edit log keeps the history.</p>
      <button type="button" className="btn btn--primary" disabled={disabled} onClick={() => run("fresh")}>
        start fresh
      </button>
      <button type="button" className="btn btn--outline" autoFocus onClick={() => setStep("choose")}>
        back
      </button>
    </div>
  );
}
