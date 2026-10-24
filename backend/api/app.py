"""The http layer, four routes and a job runner behind them."""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.routing import APIRoute

from backend.analysis.ffmpeg_tools import ToolNotFoundError, find_tool
from backend.analysis.ingest import FileTooLargeError, UnsupportedFileError, check_extension, ingest_stream
from backend.api.jobs import JobRunner
from backend.api.models import Health, JobCreated, JobStatus
from backend.api.settings import Settings
from backend.api.storage import JobStore
from backend.schema.models import TimingReport

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
        yield
        runner.shutdown()

    app = FastAPI(title="starstep-meter", lifespan=lifespan)
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

    @router.get("/jobs/{job_id}", response_model=JobStatus)
    def get_job(job_id: str) -> JobStatus:
        status = store.read_status(job_id)
        if status is None:
            raise HTTPException(404, "job not found")
        return status

    @router.get("/jobs/{job_id}/report", response_model=TimingReport)
    def get_report(job_id: str) -> TimingReport:
        status = store.read_status(job_id)
        if status is None:
            raise HTTPException(404, "job not found")
        if status.status == "failed":
            error = status.error
            where = f"{error.stage}: {error.message}" if error else "unknown stage"
            raise HTTPException(409, f"job failed at {where}")
        if status.status != "done":
            raise HTTPException(409, f"report not ready, job is at {status.stage}")
        return store.read_report(job_id)

    @router.get("/health", response_model=Health)
    def health() -> Health:
        return Health(
            status="ok",
            ffmpeg=find_tool("ffmpeg") is not None,
            ffprobe=find_tool("ffprobe") is not None,
            # find_spec only looks, importing madmom is slow and can fail on some setups
            madmom=importlib.util.find_spec("madmom") is not None,
        )

    app.include_router(router)
    return app


app = create_app()
