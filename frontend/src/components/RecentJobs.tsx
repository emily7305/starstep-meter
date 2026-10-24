import { useEffect } from "react";
import { ensureJapaneseFont } from "../fonts";
import { formatEditCount, formatJobDate } from "../jobs";
import type { JobSummary } from "../types/api";

interface Props {
  jobs: JobSummary[] | null;
  currentId: string | null;
  error: string | null;
  onOpen: (jobId: string) => void;
}

export function RecentJobs({ jobs, currentId, error, onOpen }: Props) {
  useEffect(() => {
    for (const job of jobs ?? []) ensureJapaneseFont(job.filename);
  }, [jobs]);

  // both can be set, a failed refresh doesn't have to hide the last list
  const errorLine = error === null ? null : <p className="recent__error">{error}</p>;

  if (jobs === null) return errorLine;

  return (
    <>
      {errorLine}
      {jobs.length === 0 ? (
        <p className="empty empty--small">no jobs yet</p>
      ) : (
        <ol className="recent" aria-label="recent jobs">
          {jobs.map((job) => (
            <li key={job.job_id} className="recent__item">
              <button
                type="button"
                className="recent__row"
                aria-current={job.job_id === currentId ? "true" : undefined}
                onClick={() => onOpen(job.job_id)}
              >
                <span className="recent__name mono" title={job.filename}>
                  {job.filename}
                </span>
                <span className="recent__meta mono">
                  <span className="recent__date">{formatJobDate(job.created_at)}</span>
                  {job.status !== "done" && (
                    <span className="recent__status" data-status={job.status}>
                      {job.status}
                    </span>
                  )}
                  {job.edits !== null && job.edits > 0 && (
                    <span className="recent__edits">{formatEditCount(job.edits)}</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
