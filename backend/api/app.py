"""The http layer, a handful of routes and a job runner behind them."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from backend.analysis.beats import madmom_available, madmom_import_error
from backend.analysis.ffmpeg_tools import ToolNotFoundError, find_tool
from backend.analysis.ingest import FileTooLargeError, UnsupportedFileError, check_extension, ingest_stream
from backend.analysis.tempo_edit import TempoEditError
from backend.api.jobs import JobRunner
from backend.api.models import Health, JobCreated, JobStatus, JobSummary, TempoEdit
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.api.tempo_patch import apply_tempo_edit
from backend.schema.models import SCHEMA_VERSION, BeatsFile, TimingReport

# multipart boundaries and part headers add a few hundred bytes on top of the file
# only reject on the header when it's over the limit by more than that, ingest counts the real bytes
_MULTIPART_SLACK = 64 * 1024


def _body_limited_route(settings: Settings) -> type[APIRoute]:
    # the form is parsed before a route function runs, so a size check in the route
    # would only fire after the whole upload was already spooled to disk
    # wrapping the handler is the one place that's still ahead of the body
    # ngl a custom route class feels heavy for a size check, couldn't find a lighter way
    class BodyLimitedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handle = super().get_route_handler()

            async def limited(request: Request) -> Response:
                try:
                    declared = int(request.headers.get("content-length", ""))
                except ValueError:
                    declared = 0
                if declared > settings.max_upload_bytes + _MULTIPART_SLACK:
                    raise HTTPException(413, f"file is larger than the {settings.max_upload_mb} MB limit")
                return await handle(request)

            return limited

    return BodyLimitedRoute


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = JobStore(settings.jobs_dir)
    # the pool is shut down with the app, so one app is one lifespan, tests build a fresh one each time
    runner = JobRunner(store, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runner.recover()
        # warm the cache, the import takes about a second and the first health check shouldn't pay for it
        madmom_import_error()
        yield
        runner.shutdown()

    app = FastAPI(title="starstep-meter", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # fastapi's own handler echoes the bad input back, and a NaN in there can't be
        # written as json, so the client got a 500 instead of the 422. drop the echo
        errors = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})
    # no cors middleware, the frontend dev server proxies /api
    router = APIRouter(prefix="/api", route_class=_body_limited_route(settings))

    @router.post("/jobs", status_code=202, response_model=JobCreated)
    def create_job(file: UploadFile | None = File(None)) -> JobCreated:
        if file is None:
            raise HTTPException(400, "no file in the upload, expected a multipart field named file")
        filename = file.filename or ""
        try:
            check_extension(filename)
        except UnsupportedFileError as exc:
            raise HTTPException(415, str(exc)) from exc
        # checked up front so a missing ffprobe doesn't leave a job dir behind
        if find_tool("ffprobe") is None:
            raise HTTPException(503, "ffprobe not found on PATH")

        job_id, job_dir = store.create()
        stored = False
        try:
            ingested = ingest_stream(file.file, filename, job_dir, settings.max_upload_bytes)
            store.write_job(job_id, filename, ingested.sha256, ingested.size_bytes)
            store.write_status(job_id, JobStatus(status="queued", stage="queued"))
            stored = True
        except FileTooLargeError as exc:
            raise HTTPException(413, str(exc)) from exc
        except UnsupportedFileError as exc:
            raise HTTPException(415, str(exc)) from exc
        except ToolNotFoundError as exc:
            raise HTTPException(503, str(exc)) from exc
        finally:
            if not stored:
                store.remove(job_id)

        runner.submit(job_id)
        return JobCreated(job_id=job_id)

    @router.get("/jobs", response_model=list[JobSummary])
    def list_jobs(sha256: str | None = Query(None, pattern=r"^[0-9a-f]{64}$")) -> list[JobSummary]:
        # newest first. with sha256, only the jobs for that exact file, so the ui can offer to reopen one
        return store.summaries(sha256)

    @router.get("/jobs/{job_id}", response_model=JobStatus)
    def get_job(job_id: str) -> JobStatus:
        status = store.read_status(job_id)
        if status is None:
            raise HTTPException(404, "job not found")
        return status

    def require_done(job_id: str, what: str) -> None:
        status = store.read_status(job_id)
        if status is None:
            raise HTTPException(404, "job not found")
        if status.status == "failed":
            error = status.error
            where = f"{error.stage}: {error.message}" if error else "unknown stage"
            raise HTTPException(409, f"job failed at {where}")
        if status.status != "done":
            raise HTTPException(409, f"{what} not ready, job is at {status.stage}")

    def stale_report(exc: ValidationError) -> HTTPException:
        # a job from before a schema bump, the report can't be read as the current version
        return HTTPException(409, f"stored report doesn't match schema {SCHEMA_VERSION}, upload the file again")

    @router.get("/jobs/{job_id}/report", response_model=TimingReport)
    def get_report(job_id: str) -> TimingReport:
        require_done(job_id, "report")
        try:
            return store.read_report(job_id)
        except ValidationError as exc:
            raise stale_report(exc) from exc

    @router.patch("/jobs/{job_id}/report", response_model=TimingReport)
    def patch_report(job_id: str, body: TempoEdit) -> TimingReport:
        # one tempo map edit per call, every real change lands in edits
        require_done(job_id, "report")
        try:
            beats = store.read_beats(job_id)
        except (OSError, ValidationError):
            # split and merge keep the old grid instead of refitting, nothing else needs the beats
            beats = None

        def apply(report: TimingReport) -> TimingReport:
            try:
                return apply_tempo_edit(report, body, beats, datetime.now(timezone.utc))
            except TempoEditError as exc:
                raise HTTPException(422, str(exc)) from exc

        try:
            return store.update_report(job_id, apply)
        except ValidationError as exc:
            raise stale_report(exc) from exc

    @router.post("/jobs/{job_id}/reanalyze", status_code=202, response_model=JobCreated)
    def reanalyze(job_id: str) -> JobCreated:
        # runs the analysis again on the stored upload, manual segments and the edit log carry over
        status = store.read_status(job_id)
        if status is None:
            raise HTTPException(404, "job not found")
        if status.status in ("queued", "running"):
            raise HTTPException(409, f"job is still at {status.stage}")
        if store.find_original(job_id) is None:
            raise HTTPException(409, "the original upload is missing, upload the file again")
        store.write_status(job_id, JobStatus(status="queued", stage="queued"))
        runner.submit(job_id)
        return JobCreated(job_id=job_id)

    @router.get("/jobs/{job_id}/beats", response_model=BeatsFile)
    def get_beats(job_id: str) -> BeatsFile:
        require_done(job_id, "beats")
        try:
            return store.read_beats(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(409, "no beats file for this job, upload the file again") from exc
        except ValidationError as exc:
            raise HTTPException(409, f"stored beats don't match schema {SCHEMA_VERSION}, upload the file again") from exc

    @router.get("/jobs/{job_id}/audio")
    def get_audio(job_id: str) -> FileResponse:
        # the decoded wav, for playback in the local ui only. it's the file the analysis ran on,
        # so the waveform and the timing numbers share one timeline
        require_done(job_id, "audio")
        path = store.decoded_path(job_id)
        if not path.is_file():
            raise HTTPException(404, "decoded audio is missing")
        return FileResponse(path, media_type="audio/wav")

    @router.get("/health", response_model=Health)
    def health() -> Health:
        # cached since startup. none when madmom isn't installed, that isn't an import error
        madmom_error = madmom_import_error()
        return Health(
            status="ok",
            ffmpeg=find_tool("ffmpeg") is not None,
            ffprobe=find_tool("ffprobe") is not None,
            madmom=madmom_available() and madmom_error is None,
            madmom_error=madmom_error,
        )

    app.include_router(router)
    return app


app = create_app()
