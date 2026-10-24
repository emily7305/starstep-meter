# architecture

Three parts: a pure-Python analysis pipeline, a thin FastAPI server around it, and a React frontend. The pipeline doesn't know the server exists, so every stage can be run and tested from the command line.

## pipeline (`backend/analysis/`)

Each stage is a plain function that takes paths or numpy arrays and returns a small dataclass.

| module | in | out |
| --- | --- | --- |
| `ingest.py` | upload stream or file path, job dir | `IngestResult`: stored original, sha256, size, ffprobe info |
| `decode.py` | original file | `decoded.wav` (mono float32, native rate) and `DecodedAudio` |
| `trim.py` | samples, sample rate | `TrimResult`: `start_ms`, `end_ms` |
| `tempo.py` | samples, sample rate, trim bounds | `TempoResult`: one bpm plus debug numbers |
| `pipeline.py` | original, work dir, filename, sha256 | `AnalysisOutput` with the `TimingReport` |
| `cli.py` | file path | report JSON on stdout |

`ffmpeg_tools.py` finds and runs ffmpeg/ffprobe (`shutil.which`, argument lists, never a shell). A missing tool raises `ToolNotFoundError("ffmpeg not found on PATH")`.

`run_analysis` calls `on_stage("decode" | "trim" | "tempo")` as it goes and wraps any failure in `StageError(stage, message)`, so the caller always knows where it broke. Ingest isn't a job stage. It runs during the upload request, so a bad file is rejected with a 4xx straight away instead of becoming a failed job.

All times are milliseconds from the first decoded sample. Trim only reports boundaries and never cuts the audio, so later stages and the frontend share one timeline.

## server (`backend/api/`)

- `app.py`: `create_app(settings)` and the four routes. `POST /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/report`, `GET /api/health`.
- `jobs.py`: a `ThreadPoolExecutor` (one worker by default) runs `run_analysis` and writes status as stages change.
- `storage.py`: job directories and atomic JSON writes.
- `settings.py`: data dir, upload limit, trim threshold, worker count, all overridable with `STARSTEP_*` env vars.
- `python -m backend.api` starts uvicorn on 127.0.0.1:8000.

Job storage, one directory per job under `data/jobs/<job_id>/`:

```
original.<ext>   the upload as received
decoded.wav      ffmpeg output the analysis ran on
job.json         filename, sha256, size, created_at
status.json      {status, stage, error}, rewritten on every stage change
report.json      the timing report, once done
```

Status and report are on disk, so a restart doesn't lose finished jobs. Jobs that were still queued or running when the server stopped are marked failed on the next start ("server restarted before the job finished"). There's no Celery, Redis, or database.

`status` is `queued | running | done | failed`. `stage` is `queued | decode | trim | tempo | done | failed`. A failure keeps the stage it happened in as `error.stage`.

## schema (`backend/schema/`, `shared/schema/`)

`models.py` is the source of truth for the timing report (v1.0, see `schema-changelog.md`). `export_schema.py` writes `shared/schema/timing_report.schema.json`, which is committed. The frontend generates `frontend/src/types/timingReport.ts` from that file with `npm run gen:types`.

Two checks keep the three in sync. A pytest test fails if the committed JSON Schema differs from the model, and `npm run check:types` fails if the committed TypeScript differs from what the JSON Schema generates.

Rules that hold from now on:

- Every tempo/meter/section segment has `source: "auto" | "manual"`. Re-analysis only replaces auto segments.
- `edits` is append-only and records every manual change.
- Beats go in their own file next to `report.json`, not inside the report.
- Breaking changes bump `schema_version` and get a changelog entry.

## frontend (`frontend/`)

Vite + React + TypeScript. In dev, Vite proxies `/api` to the backend, so there's no CORS setup.

- Upload goes through `XMLHttpRequest` because fetch can't report upload progress.
- `poll.ts` holds the polling loop as a plain async function with an injectable sleep. It's the part with a vitest test.
- The page is laid out around the timeline. It's a full-width band at the top, empty in milestone 1, and the waveform goes there in milestone 2. Controls and the report sit underneath.

## tests (`tests/`)

`synth.py` generates click tracks with known onsets, padding, an optional noise floor and accented downbeats. WAVs are cached in `tests/fixtures/` (git-ignored), keyed on a hash of the generator source and the spec. Tests that need ffmpeg carry `@pytest.mark.ffmpeg` and are skipped when it's missing.
