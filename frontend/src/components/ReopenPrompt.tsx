import { formatEditCount, formatJobDate } from "../jobs";
import type { JobSummary } from "../types/api";

interface Props {
  matches: JobSummary[];
  onReopen: (jobId: string) => void;
  onFresh: () => void;
  busy: boolean;
}

export function ReopenPrompt({ matches, onReopen, onFresh, busy }: Props) {
  // matches come newest first, as the api sends them, so the first row is the newest
  return (
    <div className="reopen">
      <p className="reopen__lead">this file was analyzed before</p>
      <ol className="reopen__list">
        {matches.map((job, i) => (
          <li key={job.job_id} className="reopen__item">
            <span className="reopen__info mono">
              <span className="reopen__date">{formatJobDate(job.created_at)}</span>
              <span className="reopen__edits">{formatEditCount(job.edits ?? 0)}</span>
              {job.status !== "done" && (
                <span className="reopen__status" data-status={job.status}>
                  {job.status}
                </span>
              )}
            </span>
            <button
              type="button"
              className={i === 0 ? "btn btn--primary" : "btn btn--outline"}
              disabled={busy}
              onClick={() => onReopen(job.job_id)}
            >
              reopen
            </button>
          </li>
        ))}
      </ol>
      <button type="button" className="btn btn--outline" disabled={busy} onClick={onFresh}>
        analyze again as a new job
      </button>
    </div>
  );
}
