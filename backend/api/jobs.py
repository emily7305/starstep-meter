"""Runs analysis jobs on a small thread pool and keeps status.json current."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import cast

from backend.analysis.pipeline import DECODED_NAME, AnalysisConfig, Stage, StageError, run_analysis
from backend.api.models import ErrorStage, JobError, JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import TimingReport

log = logging.getLogger("starstep.jobs")

RESTART_MESSAGE = "server restarted before the job finished"
_ERROR_STAGES = ("queued", "decode", "trim", "beats", "snap", "tempo", "meter")


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
        )
        # no celery or redis, the job dirs on disk are the only state
        self._executor = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="analysis")

    def submit(self, job_id: str) -> Future[None]:
        return self._executor.submit(self._run, job_id)

    def recover(self) -> int:
        # whatever was queued or running died with the old process, say so instead of polling forever
        # todo: re-queue jobs that were only queued instead of failing them
        recovered = 0
        for job_id in self._store.job_ids():
            try:
                # a re-analysis that died mid-run leaves its staging folder behind
                self._store.clear_rerun(job_id)
                status = self._store.read_status(job_id)
                if status is None or status.status not in ("queued", "running"):
                    continue
                self._mark_failed(job_id, _error_stage(status.stage), RESTART_MESSAGE)
                recovered += 1
            except (OSError, ValueError):
                log.warning("skipping job %s, could not read or update its status.json", job_id)
        if recovered:
            log.warning("marked %d unfinished job(s) as failed after a restart", recovered)
        return recovered

    def shutdown(self) -> None:
        # a job that's mid-analysis keeps going, queued ones stay queued on disk and recover() deals with them
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
            last_stage = _error_stage(stage)
            self._store.write_status(job_id, JobStatus(status="running", stage=stage))

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
            )
            if reanalysis:
                self._store.replace_decoded(job_id, work_dir / DECODED_NAME)
                # gone before done can be seen, nothing needs it past the move
                self._store.clear_rerun(job_id)
            # beats and report first, so "done" is never visible without something to fetch
            self._store.write_beats(job_id, out.beats)
            self._store.write_report(job_id, out.report)
            self._store.write_status(job_id, JobStatus(status="done", stage="done"))
        except StageError as exc:
            log.info("job %s failed at %s: %s", job_id, exc.stage, exc.message)
            self._record_failure(job_id, _error_stage(exc.stage), exc.message)
        except Exception as exc:
            log.exception("job %s crashed outside the pipeline", job_id)
            self._record_failure(job_id, last_stage, str(exc) or type(exc).__name__)
