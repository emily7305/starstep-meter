import { useEffect, useMemo, useState } from "react";
import { ensureJapaneseFont } from "../fonts";
import { formatEditCount, formatJobDate, groupJobs, type JobGroup } from "../jobs";
import type { JobSummary } from "../types/api";

interface Props {
  jobs: JobSummary[] | null;
  currentId: string | null;
  error: string | null;
  onOpen: (jobId: string) => void;
  // resolves to the failure text, null when the job is gone
  onDelete: (jobId: string) => Promise<string | null>;
}

// the server refuses these with a 409, so the button isn't offered
function isDeletable(job: JobSummary): boolean {
  return job.status !== "queued" && job.status !== "running";
}

function JobMeta({ job, className }: { job: JobSummary; className?: string }) {
  return (
    <span className={className === undefined ? "recent__meta mono" : `recent__meta ${className} mono`}>
      <span className="recent__date" title="when the song was uploaded">
        {formatJobDate(job.created_at)}
      </span>
      {job.reanalyzed_at !== null && (
        <span className="recent__again">re-analyzed at {formatJobDate(job.reanalyzed_at)}</span>
      )}
      {job.status !== "done" && (
        <span className="recent__status" data-status={job.status}>
          {job.status}
        </span>
      )}
      {job.edits !== null && job.edits > 0 && <span className="recent__edits">{formatEditCount(job.edits)}</span>}
    </span>
  );
}

export function RecentJobs({ jobs, currentId, error, onOpen, onDelete }: Props) {
  // one row at a time asks for confirmation, and only that row can be waiting on the server
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<{ id: string; text: string } | null>(null);
  // by sha256, only what the user toggled, the rest follows the default in isOpen
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => groupJobs(jobs ?? []), [jobs]);

  // older rows show no file name, so the latest job's is the only one to cover
  useEffect(() => {
    for (const group of groups) ensureJapaneseFont(group.latest.filename);
  }, [groups]);

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

  // a current job among the older ones would otherwise be hidden
  const isOpen = (group: JobGroup) =>
    toggled[group.sha256] ?? group.older.some((job) => job.job_id === currentId);

  const toggle = (group: JobGroup) => setToggled((prev) => ({ ...prev, [group.sha256]: !isOpen(group) }));

  // label tells the delete buttons of one file apart for a screen reader
  const deleteButton = (job: JobSummary, label: string) =>
    isDeletable(job) &&
    confirmId !== job.job_id && (
      <button
        type="button"
        className="btn btn--link recent__delete"
        aria-label={`delete ${label}`}
        title="delete the job with its upload, wav and edits, it asks first"
        onClick={() => askToDelete(job.job_id)}
      >
        delete
      </button>
    );

  const deleteFollowUp = (job: JobSummary, label: string) => (
    <>
      {isDeletable(job) && confirmId === job.job_id && (
        <div className="recent__confirm" role="group" aria-label={`delete ${label}`}>
          <span className="recent__ask">delete this job and its files?</span>
          <button
            type="button"
            className="btn btn--outline"
            disabled={deleting}
            onClick={() => void confirmDelete(job.job_id)}
          >
            delete
          </button>
          <button type="button" className="btn btn--outline" disabled={deleting} onClick={cancelDelete}>
            cancel
          </button>
        </div>
      )}
      {deleteError !== null && deleteError.id === job.job_id && (
        <p className="recent__error recent__error--row">{deleteError.text}</p>
      )}
    </>
  );

  return (
    <>
      {errorLine}
      {groups.length === 0 ? (
        <p className="empty empty--small">no jobs yet, analyzed songs show up here</p>
      ) : (
        <ol className="recent" aria-label="recent jobs">
          {groups.map((group) => {
            const { latest, older } = group;
            const open = isOpen(group);
            return (
              <li key={group.sha256} className="recent__item">
                <div className="recent__line">
                  <button
                    type="button"
                    className="recent__row"
                    aria-current={latest.job_id === currentId ? "true" : undefined}
                    title="open this job, its edits come with it"
                    onClick={() => onOpen(latest.job_id)}
                  >
                    <span className="recent__name mono" title={latest.filename}>
                      {latest.filename}
                    </span>
                    <JobMeta job={latest} />
                  </button>
                  {older.length > 0 && (
                    <button
                      type="button"
                      className="btn btn--link recent__toggle mono"
                      aria-expanded={open}
                      title="show the earlier analyses of this file"
                      onClick={() => toggle(group)}
                    >
                      {older.length + 1} analyses
                    </button>
                  )}
                  {deleteButton(latest, latest.filename)}
                </div>
                {deleteFollowUp(latest, latest.filename)}
                {open && older.length > 0 && (
                  <ol className="recent__older" aria-label={`earlier analyses of ${latest.filename}`}>
                    {older.map((job) => {
                      const label = `${job.filename} from ${formatJobDate(job.created_at)}`;
                      return (
                        <li
                          key={job.job_id}
                          className="recent__older-item"
                          data-current={job.job_id === currentId ? "true" : undefined}
                        >
                          <div className="recent__line recent__line--older">
                            <JobMeta job={job} className="recent__older-info" />
                            <button
                              type="button"
                              className="btn btn--link recent__open"
                              aria-current={job.job_id === currentId ? "true" : undefined}
                              aria-label={`open ${label}`}
                              title="open this earlier analysis, its edits come with it"
                              onClick={() => onOpen(job.job_id)}
                            >
                              open
                            </button>
                            {deleteButton(job, label)}
                          </div>
                          {deleteFollowUp(job, label)}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
