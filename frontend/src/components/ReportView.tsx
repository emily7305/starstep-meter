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

function editValue(field: string, value: unknown): string {
  if (value === null) return "–";
  // split and merge log the whole map
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "segment" : "segments"}`;
  if (typeof value === "number") {
    if (field.endsWith("/bpm")) return `${value} bpm`;
    if (field.endsWith("/confidence")) return value.toFixed(3);
    return formatFineMs(value);
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

function editTime(edit: Edit): string {
  const date = new Date(edit.timestamp);
  return Number.isNaN(date.getTime()) ? edit.timestamp : date.toLocaleTimeString([], { hour12: false });
}

export function ReportView({ report, beats }: Props) {
  if (report === null) return <p className="empty">no file yet</p>;

  const { source, trim, tempo_map, edits } = report;
  const first = tempo_map[0];
  const single = tempo_map.length === 1;
  let note = "";
  if (beats !== null) note = `${beats.beats.length} beats · ${beats.tracker === "librosa" ? "librosa fallback" : "madmom"}`;
  if (beats !== null && beats.octave !== "kept") note += ` · octave ${beats.octave}`;
  if (single && first.confidence !== null) note += `${note ? " · " : ""}confidence ${first.confidence.toFixed(2)}`;
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
          label="first downbeat"
          value={formatFineMs(first.anchor_ms)}
          note={first.source === "manual" ? "edited" : undefined}
        />
        <div className="row row--bpm">
          <dt>{single ? "bpm" : "tempo"}</dt>
          <dd>
            <span className="row__bpm mono">{single ? formatBpm(first.bpm) : `${tempo_map.length} segments`}</span>
            {note && <span className="row__note mono">{note}</span>}
          </dd>
        </div>
        <Row label="sha256" value={`${source.sha256.slice(0, 12)}…`} title={source.sha256} />
      </dl>

      {beats?.tracker === "librosa" && (
        <p className="report__warn">
          madmom isn't installed, so beats come from librosa, the downbeat is a guess and tempo changes aren't followed
        </p>
      )}

      <h3 className="subsection-label">tempo map</h3>
      <ol className="segments">
        {tempo_map.map((seg, i) => (
          <li key={`${seg.start_ms}-${i}`} className="segments__item mono">
            <span className="segments__index">{i + 1}</span>
            <span className="segments__start">{formatMs(seg.start_ms)}</span>
            <span className="segments__bpm">{formatBpm(seg.bpm)}</span>
            <span className="segments__meta">
              {seg.source === "manual" ? "manual" : seg.confidence === null ? "auto" : `auto ${seg.confidence.toFixed(2)}`}
            </span>
            {seg.ratio_merged.map((note) => (
              <span key={`${note.start_ms}-${note.end_ms}`} className="segments__felt">
                kept {formatBpm(note.bpm)} ({note.ratio}) from {formatMs(note.start_ms)} to {formatMs(note.end_ms)}
              </span>
            ))}
          </li>
        ))}
      </ol>

      <h3 className="subsection-label">edits</h3>
      {edits.length === 0 ? (
        <p className="empty empty--small">no edits</p>
      ) : (
        <ol className="edits" start={edits.length - shown.length + 1}>
          {shown.map((edit, i) => (
            <li key={`${edit.timestamp}-${i}`} className="edits__item mono">
              <span className="edits__field">{edit.field}</span>
              <span className="edits__change">
                {editValue(edit.field, edit.old)} → {editValue(edit.field, edit.new)}
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
