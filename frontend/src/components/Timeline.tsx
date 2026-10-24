import { formatMs } from "../format";
import type { TimingReport } from "../types/timingReport";

interface Props {
  report: TimingReport | null;
}

// empty on purpose, the waveform goes in here later
export function Timeline({ report }: Props) {
  return (
    <section className="timeline" aria-label="timeline">
      <div className="timeline__ruler" aria-hidden="true" />
      <div className="timeline__center" aria-hidden="true" />
      <div className="timeline__playhead" aria-hidden="true">
        <svg className="timeline__cap" viewBox="0 0 12 12" width="12" height="12">
          <path d="M6 0L12 6L6 12L0 6Z" fill="currentColor" />
        </svg>
      </div>
      <span className="timeline__label">timeline</span>
      <div className="timeline__body">
        {report === null ? (
          <p className="timeline__placeholder">no audio loaded</p>
        ) : (
          <p className="timeline__placeholder timeline__placeholder--loaded">
            <span className="mono">{report.source.filename}</span>
            <span className="mono">{formatMs(report.source.duration_ms)}</span>
          </p>
        )}
      </div>
    </section>
  );
}
