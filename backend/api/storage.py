"""Job folders on disk, one per upload, with small json files next to the audio."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

from backend.analysis.ingest import ALLOWED_EXTENSIONS
from backend.api.models import JobStatus, JobSummary
from backend.analysis.pipeline import DECODED_NAME
from backend.schema.migrate import upgrade_beats, upgrade_report
from backend.schema.models import BeatsFile, TimingReport

JOB_FILE = "job.json"
STATUS_FILE = "status.json"
REPORT_FILE = "report.json"
BEATS_FILE = "beats.json"
# where a re-analysis works, so a failed one leaves the folder as it was
RERUN_DIR = ".rerun"

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_REPLACE_TRIES = 5


class JobNotFoundError(LookupError):
    pass


class JobRecord(BaseModel):
    job_id: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: str
    # when a re-analysis last finished, the job moves up the recent list then
    reanalyzed_at: str | None = None
    # the generated demo track, the recent list leaves it out
    demo: bool = False


class _StatusFile(JobStatus):
    updated_at: str


def new_job_id() -> str:
    return uuid.uuid4().hex


def is_job_id(value: str) -> bool:
    # fullmatch, because $ alone lets a trailing newline through
    return _JOB_ID.fullmatch(value) is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _aware(stamp: datetime) -> datetime:
    # a hand edited file might drop the offset, read that as utc rather than fail to compare
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)


def _replace_with_retry(src: Path, dst: Path) -> None:
    # windows raises PermissionError if a reader has dst open at that exact moment
    # it clears up almost immediately, so a few short retries is enough
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(0.02 * (attempt + 1))


def _write_atomic(path: Path, text: str) -> None:
    # temp file in the same dir, os.replace so a crash mid-write never leaves half a status.json behind
    # no fsync, tbh a power cut mid-job just means uploading it again
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        # write_bytes, write_text would turn \n into \r\n on windows
        tmp.write_bytes(text.encode("utf-8"))
        _replace_with_retry(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class JobStore:
    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir
        # one lock for every report read-modify-write. holding a key down in the ui sends
        # patches faster than they finish, and two of them reading the same old report
        # would silently drop an edit
        self._report_lock = threading.Lock()

    def create(self) -> tuple[str, Path]:
        job_id = new_job_id()
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True)
        return job_id, job_dir

    def job_dir(self, job_id: str) -> Path:
        # nothing user supplied becomes a path before it passes this
        if not is_job_id(job_id):
            raise JobNotFoundError(job_id)
        return self.jobs_dir / job_id

    def remove(self, job_id: str) -> None:
        # ignore_errors, windows can still be holding a file for a moment and this is only cleanup
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def delete(self, job_id: str) -> None:
        """Delete one job folder for good. Raises OSError when a file in it can't go, e.g. one still open on windows."""
        job_dir = self.job_dir(job_id)
        if not job_dir.is_dir():
            raise JobNotFoundError(job_id)
        # under the report lock, so an edit can't be halfway through writing into it
        with self._report_lock:
            shutil.rmtree(job_dir)

    def last_activity(self, job_id: str) -> datetime:
        """When the job last changed: the upload, a status change or an edit.

        Exports and plain reads don't count. A folder where none of those can be read
        goes by its own mtime, which covers an upload that never finished.
        """
        job_dir = self.job_dir(job_id)
        stamps: list[datetime] = []
        try:
            stamps.append(datetime.fromisoformat(self.read_job(job_id).created_at))
        except (OSError, ValueError):
            pass
        try:
            status = _StatusFile.model_validate_json((job_dir / STATUS_FILE).read_text(encoding="utf-8"))
            stamps.append(datetime.fromisoformat(status.updated_at))
        except (OSError, ValueError):
            pass
        try:
            edits = self.read_report(job_id).edits
            if edits:
                stamps.append(edits[-1].timestamp)
        except (OSError, ValueError):
            pass
        if not stamps:
            stamps.append(datetime.fromtimestamp(job_dir.stat().st_mtime, timezone.utc))
        return max(_aware(s) for s in stamps)

    def remove_expired(self, now: datetime, retention: timedelta) -> list[str]:
        """Delete every job folder that hasn't changed within retention, its decoded wav with it."""
        removed = []
        for job_id in self.job_ids():
            try:
                expired = self.last_activity(job_id) < now - retention
            except OSError:
                # gone or unreadable since the listing, nothing to judge it by
                continue
            if expired:
                self.remove(job_id)
                removed.append(job_id)
        return removed

    def job_ids(self) -> list[str]:
        if not self.jobs_dir.is_dir():
            return []
        return sorted(p.name for p in self.jobs_dir.iterdir() if p.is_dir() and is_job_id(p.name))

    def find_original(self, job_id: str) -> Path | None:
        job_dir = self.job_dir(job_id)
        for ext in ALLOWED_EXTENSIONS:
            candidate = job_dir / f"original{ext}"
            if candidate.is_file():
                return candidate
        return None

    def write_job(self, job_id: str, filename: str, sha256: str, size_bytes: int, demo: bool = False) -> JobRecord:
        record = JobRecord(
            job_id=job_id, filename=filename, sha256=sha256, size_bytes=size_bytes, created_at=_utc_now(), demo=demo
        )
        _write_atomic(self.job_dir(job_id) / JOB_FILE, record.model_dump_json(indent=2) + "\n")
        return record

    def read_job(self, job_id: str) -> JobRecord:
        text = (self.job_dir(job_id) / JOB_FILE).read_text(encoding="utf-8")
        return JobRecord.model_validate_json(text)

    def mark_reanalyzed(self, job_id: str) -> None:
        record = self.read_job(job_id).model_copy(update={"reanalyzed_at": _utc_now()})
        _write_atomic(self.job_dir(job_id) / JOB_FILE, record.model_dump_json(indent=2) + "\n")

    def write_status(self, job_id: str, status: JobStatus) -> None:
        # report_available is worked out when the status is read, a stored copy would go stale
        stored = _StatusFile(**status.model_dump(exclude={"report_available"}), updated_at=_utc_now())
        _write_atomic(
            self.job_dir(job_id) / STATUS_FILE,
            stored.model_dump_json(indent=2, exclude={"report_available"}) + "\n",
        )

    def read_status(self, job_id: str) -> JobStatus | None:
        # a folder with no status.json is an upload that never finished, same as no job
        # todo: sweep those on startup, a crash mid-upload leaves them behind
        if not is_job_id(job_id):
            return None
        try:
            text = (self.job_dir(job_id) / STATUS_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return JobStatus.model_validate_json(text)

    def has_report(self, job_id: str) -> bool:
        return (self.job_dir(job_id) / REPORT_FILE).is_file()

    def write_report(self, job_id: str, report: TimingReport) -> None:
        _write_atomic(self.job_dir(job_id) / REPORT_FILE, report.model_dump_json(indent=2) + "\n")

    def read_report(self, job_id: str) -> TimingReport:
        # a report from an older schema is upgraded on the way in, and written back as the
        # current one the next time something changes it
        text = (self.job_dir(job_id) / REPORT_FILE).read_text(encoding="utf-8")
        return TimingReport.model_validate(upgrade_report(json.loads(text)))

    def update_report(self, job_id: str, change: Callable[[TimingReport], TimingReport]) -> TimingReport:
        with self._report_lock:
            updated = change(self.read_report(job_id))
            self.write_report(job_id, updated)
            return updated

    def write_beats(self, job_id: str, beats: BeatsFile) -> None:
        _write_atomic(self.job_dir(job_id) / BEATS_FILE, beats.model_dump_json(indent=2) + "\n")

    def read_beats(self, job_id: str) -> BeatsFile:
        text = (self.job_dir(job_id) / BEATS_FILE).read_text(encoding="utf-8")
        return BeatsFile.model_validate(upgrade_beats(json.loads(text)))

    def summary(self, job_id: str) -> JobSummary | None:
        # None for a folder that isn't a finished upload, same as read_status
        status = self.read_status(job_id)
        if status is None:
            return None
        record = self.read_job(job_id)
        edits: int | None = None
        try:
            edits = len(self.read_report(job_id).edits)
        except (OSError, ValueError):
            # no report yet, or one from before 1.1 that can't be read any more
            pass
        return JobSummary(
            job_id=job_id,
            filename=record.filename,
            sha256=record.sha256,
            size_bytes=record.size_bytes,
            created_at=record.created_at,
            reanalyzed_at=record.reanalyzed_at,
            status=status.status,
            edits=edits,
            demo=record.demo,
        )

    def summaries(self, sha256: str | None = None) -> list[JobSummary]:
        out = []
        for job_id in self.job_ids():
            try:
                summary = self.summary(job_id)
            except (OSError, ValueError):
                # a half-written or hand-broken job folder shouldn't hide all the others
                continue
            if summary is not None and (sha256 is None or summary.sha256 == sha256):
                out.append(summary)
        # iso timestamps in utc sort as text, newest first. a re-analysis counts as new, it's the
        # job someone is working on
        return sorted(out, key=lambda s: max(s.created_at, s.reanalyzed_at or ""), reverse=True)

    def decoded_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / DECODED_NAME

    def fresh_rerun_dir(self, job_id: str) -> Path:
        # empty, whatever an earlier run left behind is no use to this one
        self.clear_rerun(job_id)
        path = self.job_dir(job_id) / RERUN_DIR
        path.mkdir()
        return path

    def clear_rerun(self, job_id: str) -> None:
        # ignore_errors, same as remove, this only ever cleans up
        shutil.rmtree(self.job_dir(job_id) / RERUN_DIR, ignore_errors=True)

    def replace_decoded(self, job_id: str, staged: Path) -> None:
        # a player can have the old wav open, which is what the retry is for on windows
        _replace_with_retry(staged, self.decoded_path(job_id))
