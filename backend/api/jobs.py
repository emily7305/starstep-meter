"""Runs analysis jobs on a small thread pool and keeps status.json current."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import cast

from backend.analysis.cross_check import CrossCheckConfig
from backend.analysis.pipeline import DECODED_NAME, AnalysisConfig, Stage, StageError, run_analysis
from backend.api.models import ErrorStage, JobError, JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import TimingReport

log = logging.getLogger("starstep.jobs")

RESTART_MESSAGE = "server restarted before the job finished"
_ERROR_STAGES = ("queued", "decode", "trim", "beats", "snap", "tempo", "meter", "check")


class Cancelled(Exception):
    """Raised at the next stage boundary once a job was asked to stop."""


@dataclass
class _Pending:
    future: Future[None] | None = None
    # what a cancelled re-analysis goes back to, None for a first analysis
    before: JobStatus | None = None
    keep_edits: bool = True
    cancelled: bool = False


def _error_stage(stage: str) -> ErrorStage:
    # a job can't break at done or failed, so anything odd in a hand edited file reads as queued
    return cast(ErrorStage, stage) if stage in _ERROR_STAGES else "queued"


class JobRunner:
    def __init__(self, store: JobStore, settings: Settings) -> None:
        self._store = store
        self._config = AnalysisConfig(
            trim_threshold_db=settings.trim_threshold_db,
            snap_window_ms=settings.snap_window_ms,
            tempo_range=settings.tempo_range,
            cross_check=CrossCheckConfig(settings.cross_check_ms),
        )
        # no celery or redis, the job dirs on disk are the only state
        self._executor = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="analysis")
        # what the queue knows beyond the disk: start fresh and cancel. a restart forgets both, a
        # queued start fresh then keeps the edits, which loses nothing
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, keep_edits: bool = True, before: JobStatus | None = None) -> Future[None]:
        with self._lock:
            pending = _Pending(before=before, keep_edits=keep_edits)
            self._pending[job_id] = pending
            pending.future = self._executor.submit(self._run, job_id)
            return pending.future

    def cancel(self, job_id: str) -> bool:
        """Stop a queued or running job at its next stage. False when nothing is queued or running for it.

        A first analysis is deleted, a re-analysis goes back to the report and status it had.
        A running one stops when its stage ends, madmom's network can't be interrupted inside.
        """
        with self._lock:
            pending = self._pending.get(job_id)
            if pending is None:
                return False
            pending.cancelled = True
            not_started = pending.future is not None and pending.future.cancel()
        if not_started:
            self._finish_cancel(job_id, pending)
        return True

    def _finish_cancel(self, job_id: str, pending: _Pending) -> None:
        with self._lock:
            self._pending.pop(job_id, None)
        try:
            if pending.before is None:
                self._store.delete(job_id)
            else:
                self._store.clear_rerun(job_id)
                self._store.write_status(job_id, pending.before)
            log.info("job %s cancelled", job_id)
        except Exception:
            log.exception("could not finish cancelling job %s", job_id)

    def _cancelled(self, job_id: str) -> _Pending | None:
        with self._lock:
            pending = self._pending.get(job_id)
        return pending if pending is not None and pending.cancelled else None

    def recover(self) -> tuple[list[str], int]:
        """Jobs that were queued go back in the queue, ones that were running are marked failed.

        Returns the re-queued job ids and how many were marked failed.
        """
        requeued: list[str] = []
        failed = 0
        for job_id in self._store.job_ids():
            try:
                # a re-analysis that died mid-run leaves its staging folder behind
                self._store.clear_rerun(job_id)
                status = self._store.read_status(job_id)
                if status is None:
                    continue
                if status.status == "queued":
                    # nothing ran yet, so the stored upload is all it needs. a queued re-analysis
                    # still has its report, the runner sees that and keeps the manual segments
                    self.submit(job_id)
                    requeued.append(job_id)
                elif status.status == "running":
                    # it may be what took the server down, running it again on every start could loop.
                    # re-analyze in the ui runs it again by hand
                    self._mark_failed(job_id, _error_stage(status.stage), RESTART_MESSAGE)
                    failed += 1
            except (OSError, ValueError):
                log.warning("skipping job %s, could not read or update its status.json", job_id)
        if requeued:
            log.info("re-queued %d job(s) that were waiting when the server stopped", len(requeued))
        if failed:
            log.warning("marked %d unfinished job(s) as failed after a restart", failed)
        return requeued, failed

    def shutdown(self) -> None:
        # a job that's mid-analysis keeps going, queued ones stay queued on disk and recover() picks them up
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _previous_report(self, job_id: str) -> TimingReport | None:
        # on re-analysis the old report's manual segments and edit log carry over. no edits can
        # land while the job runs, patches need it done, so reading it up front is safe
        try:
            return self._store.read_report(job_id)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # a pydantic ValidationError is a ValueError too, a 1.0 report ends up here
            log.warning("job %s has a report that can't be read, re-analysing without it", job_id)
            return None

    def _mark_failed(self, job_id: str, stage: ErrorStage, message: str) -> None:
        error = JobError(stage=stage, message=message)
        self._store.write_status(job_id, JobStatus(status="failed", stage="failed", error=error))

    def _record_failure(self, job_id: str, stage: ErrorStage, message: str) -> None:
        # runs on a worker thread, nothing is going to see an exception from here
        try:
            # before the status, so failed is never visible with the staging folder still there
            self._store.clear_rerun(job_id)
            self._mark_failed(job_id, stage, message)
        except Exception:
            log.exception("could not record the failure of job %s", job_id)

    def _run(self, job_id: str) -> None:
        last_stage: ErrorStage = "queued"

        def on_stage(stage: Stage) -> None:
            nonlocal last_stage
            if self._cancelled(job_id) is not None:
                raise Cancelled("cancelled")
            last_stage = _error_stage(stage)
            self._store.write_status(job_id, JobStatus(status="running", stage=stage))

        with self._lock:
            pending = self._pending.get(job_id) or _Pending()

        try:
            record = self._store.read_job(job_id)
            original = self._store.find_original(job_id)
            if original is None:
                raise FileNotFoundError("original upload is missing")
            # a report already there means a re-analysis. it decodes into a staging folder, so a
            # failure can't leave a wav that doesn't match the report that stays
            reanalysis = self._store.has_report(job_id)
            work_dir = self._store.fresh_rerun_dir(job_id) if reanalysis else self._store.job_dir(job_id)
            out = run_analysis(
                original,
                work_dir,
                record.filename,
                record.sha256,
                on_stage=on_stage,
                config=self._config,
                previous=self._previous_report(job_id),
                keep_edits=pending.keep_edits,
            )
            if self._cancelled(job_id) is not None:
                # asked to stop during the last stage, nothing of this run is kept
                self._finish_cancel(job_id, pending)
                return
            if reanalysis:
                self._store.replace_decoded(job_id, work_dir / DECODED_NAME)
                # gone before done can be seen, nothing needs it past the move
                self._store.clear_rerun(job_id)
            # beats and report first, so "done" is never visible without something to fetch
            self._store.write_beats(job_id, out.beats)
            self._store.write_report(job_id, out.report)
            if reanalysis:
                self._store.mark_reanalyzed(job_id)
            self._store.write_status(job_id, JobStatus(status="done", stage="done"))
        except Exception as exc:
            # the pipeline wraps the cancel from on_stage in a StageError, so look at the flag
            if self._cancelled(job_id) is not None:
                self._finish_cancel(job_id, pending)
                return
            if isinstance(exc, StageError):
                log.info("job %s failed at %s: %s", job_id, exc.stage, exc.message)
                self._record_failure(job_id, _error_stage(exc.stage), exc.message)
                return
            log.exception("job %s crashed outside the pipeline", job_id)
            self._record_failure(job_id, last_stage, str(exc) or type(exc).__name__)
        finally:
            with self._lock:
                if self._pending.get(job_id) is pending:
                    self._pending.pop(job_id, None)
