import { useEffect, useState } from "react";
import { ensureJapaneseFont } from "../fonts";
import { formatEditCount, formatJobDate } from "../jobs";
import type { JobSummary } from "../types/api";

interface Props {
  jobs: JobSummary[] | null;
  currentId: string | null;
  error: string | null;
  onOpen: (jobId: string) => void;
  // resolves to the failure text, null when the job is gone
  onDelete: (jobId: string) => Promise<string | null>;
}

export function RecentJobs({ jobs, currentId, error, onOpen, onDelete }: Props) {
  // one row at a time asks for confirmation, and only that row can be waiting on the server
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<{ id: string; text: string } | null>(null);

  useEffect(() => {
    for (const job of jobs ?? []) ensureJapaneseFont(job.filename);
  }, [jobs]);

  const askToDelete = (jobId: string) => {
    setConfirmId(jobId);
    setDeleteError(null);
  };

  const cancelDelete = () => {
    setConfirmId(null);
    setDeleteError(null);
  };

  const confirmDelete = async (jobId: string) => {
    setDeleting(true);
    setDeleteError(null);
    const failure = await onDelete(jobId);
    setDeleting(false);
    if (failure === null) setConfirmId(null);
    else setDeleteError({ id: jobId, text: failure });
  };

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
          {jobs.map((job) => {
            // the server refuses these with a 409, so the button isn't offered
            const deletable = job.status !== "queued" && job.status !== "running";
            const confirming = confirmId === job.job_id;
            return (
              <li key={job.job_id} className="recent__item">
                <div className="recent__line">
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
                  {deletable && !confirming && (
                    <button
                      type="button"
                      className="btn btn--link recent__delete"
                      aria-label={`delete ${job.filename}`}
                      onClick={() => askToDelete(job.job_id)}
                    >
                      delete
                    </button>
                  )}
                </div>
                {deletable && confirming && (
                  <div className="recent__confirm" role="group" aria-label={`delete ${job.filename}`}>
                    <span className="recent__ask">delete this job and its files?</span>
                    <button
                      type="button"
                      className="btn btn--outline"
                      disabled={deleting}
                      onClick={() => void confirmDelete(job.job_id)}
                    >
                      delete
                    </button>
                    <button
                      type="button"
                      className="btn btn--outline"
                      disabled={deleting}
                      onClick={cancelDelete}
                    >
                      cancel
                    </button>
                  </div>
                )}
                {deleteError !== null && deleteError.id === job.job_id && (
                  <p className="recent__error recent__error--row">{deleteError.text}</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
