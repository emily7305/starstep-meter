import { formatBpm, formatFineMs, formatHz, formatMs } from "../format";
import type { BeatsFile } from "../types/beats";
import type { Edit, TimingReport } from "../types/timingReport";

interface Props {
  report: TimingReport | null;
  beats: BeatsFile | null;
}

// the log can get long after a lot of nudging, the raw json still has all of it
const EDITS_SHOWN = 8;

function paddingText(samples: number, sampleRate: number): string {
  if (samples === 0) return "none";
  return `${samples} samples · ${formatFineMs((samples / sampleRate) * 1000)}`;
}

function editValue(value: unknown): string {
  return typeof value === "number" ? formatFineMs(value) : JSON.stringify(value);
}

function editTime(edit: Edit): string {
  const date = new Date(edit.timestamp);
  return Number.isNaN(date.getTime()) ? edit.timestamp : date.toLocaleTimeString([], { hour12: false });
}

export function ReportView({ report, beats }: Props) {
  if (report === null) return <p className="empty">no file yet</p>;

  const { source, trim, tempo_map, edits } = report;
  // tempo_map can be empty in theory, en dash then
  const segment = tempo_map[0];
  const confidence = segment?.confidence;
  let note = "";
  if (beats !== null) note = `${beats.beats.length} beats · ${beats.tracker === "librosa" ? "librosa fallback" : "madmom"}`;
  if (confidence !== null && confidence !== undefined) note += `${note ? " · " : ""}confidence ${confidence.toFixed(2)}`;
  const shown = edits.slice(-EDITS_SHOWN);

  return (
    <div>
      <dl className="rows">
        <Row label="file" value={source.filename} />
        <Row label="duration" value={formatMs(source.duration_ms)} />
        <Row label="sample rate" value={formatHz(source.sample_rate)} />
        <Row label="codec" value={source.codec} />
        <Row label="decoder padding" value={paddingText(source.decoder_padding_samples, source.sample_rate)} />
        <Row label="trim start" value={formatMs(trim.start_ms)} />
        <Row label="trim end" value={formatMs(trim.end_ms)} />
        <Row
          label="beat offset"
          value={report.beat_offset_ms === null ? "–" : formatFineMs(report.beat_offset_ms)}
          note={edits.length > 0 ? "edited" : undefined}
        />
        <div className="row row--bpm">
          <dt>bpm</dt>
          <dd>
            <span className="row__bpm mono">{segment === undefined ? "–" : formatBpm(segment.bpm)}</span>
            {note && <span className="row__note mono">{note}</span>}
          </dd>
        </div>
        <Row label="sha256" value={`${source.sha256.slice(0, 12)}…`} title={source.sha256} />
      </dl>

      {beats?.tracker === "librosa" && (
        <p className="report__warn">madmom isn't installed, so beats come from librosa and the downbeat is a guess</p>
      )}

      <h3 className="subsection-label">edits</h3>
      {edits.length === 0 ? (
        <p className="empty empty--small">no edits</p>
      ) : (
        <ol className="edits" start={edits.length - shown.length + 1}>
          {shown.map((edit, i) => (
            <li key={`${edit.timestamp}-${i}`} className="edits__item mono">
              <span className="edits__field">{edit.field}</span>
              <span className="edits__change">
                {editValue(edit.old)} → {editValue(edit.new)}
              </span>
              <span className="edits__time">{editTime(edit)}</span>
            </li>
          ))}
        </ol>
      )}

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
  note?: string;
}

function Row({ label, value, title, note }: RowProps) {
  return (
    <div className="row">
      <dt>{label}</dt>
      <dd className="mono" title={title}>
        {note && <span className="row__tag">{note}</span>}
        {value}
      </dd>
    </div>
  );
}
