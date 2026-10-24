import { formatBpm, formatHz, formatMs } from "../format";
import type { TimingReport } from "../types/timingReport";

interface Props {
  report: TimingReport | null;
}

export function ReportView({ report }: Props) {
  if (report === null) return <p className="empty">no file yet</p>;

  const { source, trim, tempo_map } = report;
  // tempo_map can be empty in theory, en dash then
  const bpm = tempo_map[0]?.bpm;

  return (
    <div>
      <dl className="rows">
        <Row label="file" value={source.filename} />
        <Row label="duration" value={formatMs(source.duration_ms)} />
        <Row label="sample rate" value={formatHz(source.sample_rate)} />
        <Row label="trim start" value={formatMs(trim.start_ms)} />
        <Row label="trim end" value={formatMs(trim.end_ms)} />
        <div className="row row--bpm">
          <dt>bpm</dt>
          <dd>
            <span className="row__bpm mono">{bpm === undefined ? "–" : formatBpm(bpm)}</span>
            <span className="row__note">coarse estimate</span>
          </dd>
        </div>
        <Row label="sha256" value={`${source.sha256.slice(0, 12)}…`} title={source.sha256} />
      </dl>

      <details className="raw">
        <summary>raw json</summary>
        <pre className="raw__json mono" tabIndex={0}>
          {JSON.stringify(report, null, 2)}
        </pre>
      </details>
    </div>
  );
}

interface RowProps {
  label: string;
  value: string;
  title?: string;
}

function Row({ label, value, title }: RowProps) {
  return (
    <div className="row">
      <dt>{label}</dt>
      <dd className="mono" title={title}>
        {value}
      </dd>
    </div>
  );
}
