import { useEffect, useState } from "react";
import { elapsedText } from "../format";
import { StageTrack, type TrackPosition } from "./StageTrack";

interface Props {
  // the song's file name, or the demo's
  name: string;
  demo: boolean;
  position: TrackPosition;
  // the stage it's at in words, "detecting beats"
  stageText: string;
  startedAt: number;
  cancelling: boolean;
  onCancel: () => void;
  // a song dropped while this runs waits here for a yes or no
  dropped: File | null;
  onStartDropped: () => void;
  onKeepRunning: () => void;
}

// what replaces the picker while an analysis runs, there's nothing to choose until it's done
export function Analyzing(props: Props) {
  const { name, demo, position, stageText, startedAt, cancelling, onCancel, dropped, onStartDropped, onKeepRunning } = props;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="analyzing" role="status" aria-label="analysis running">
      <p className="analyzing__name">
        <span className="analyzing__file mono">{name}</span>
        {demo && <span className="analyzing__demo">demo, a generated click track with drums</span>}
      </p>
      <StageTrack position={position} message="" />
      <p className="analyzing__line">
        {cancelling ? "cancelling, the current stage finishes first" : stageText}
        <span className="analyzing__elapsed mono" title="time since the analysis started">
          {elapsedText(now - startedAt)}
        </span>
      </p>
      <button
        type="button"
        className="btn btn--outline"
        disabled={cancelling}
        title="stop the analysis. a new song is dropped, a re-analysis keeps the report it had"
        onClick={onCancel}
      >
        cancel
      </button>
      {dropped !== null && (
        <div className="analyzing__ask" role="alertdialog" aria-label="start the dropped song instead">
          <p className="analyzing__ask-text">
            start <span className="mono">{dropped.name}</span> instead? the current analysis stops.
          </p>
          <button type="button" className="btn btn--primary" title="cancel this analysis and start the dropped song" onClick={onStartDropped}>
            start it
          </button>
          <button type="button" className="btn btn--outline" title="keep this analysis running and forget the dropped song" onClick={onKeepRunning}>
            keep the current one
          </button>
        </div>
      )}
    </div>
  );
}
