# architecture

Three parts: a pure-Python analysis pipeline, a thin FastAPI server around it, and a React frontend. The pipeline doesn't know the server exists, so every stage can be run and tested from the command line.

## pipeline (`backend/analysis/`)

Each stage is a plain function that takes paths or numpy arrays and returns a small dataclass.

| module | in | out |
| --- | --- | --- |
| `ingest.py` | upload stream or file path, job dir | `IngestResult`: stored original, sha256, size, ffprobe info |
| `decode.py` | original file | `decoded.wav` (mono float32, native rate) and `DecodedAudio` |
| `trim.py` | samples, sample rate | `TrimResult`: `start_ms`, `end_ms` |
| `beats.py` | samples, sample rate, trim bounds, tempo range | `TrackedBeats`: beat times, positions in the bar, which tracker. Also madmom's measured bias |
| `octave.py` | samples, tracked beats, rough segments | `TrackedBeats` doubled or halved per segment, and an `OctaveCheck` per segment |
| `snap.py` | samples, sample rate, beat times, bias shift | `SnapResult`: beat times moved onto onsets |
| `tempo_map.py` | snapped times, downbeat flags, trim bounds | `TempoMapResult`: segments, each with its own `GridFit` |
| `grid_fit.py` | the snapped times of one segment | `GridFit`: period, anchor, indices, residuals, confidence |
| `tempo_edit.py` | tempo segments, tracked beat times | the manual edits (split, merge, bpm, anchor) and `keep_manual_segments` for re-analysis |
| `tempo_range.py` | | `TempoRange`, the one bpm range every tempo path uses, 60–320 by default |
| `tempo.py` | samples, sample rate, trim bounds | `TempoResult`: milestone 1 bpm estimate, only used by the librosa fallback now |
| `pipeline.py` | original, work dir, filename, sha256, previous report | `AnalysisOutput` with the `TimingReport` and the `BeatsFile` |
| `cli.py` | file path | report JSON on stdout |

`ffmpeg_tools.py` finds and runs ffmpeg/ffprobe (`shutil.which`, argument lists, never a shell). A missing tool raises `ToolNotFoundError("ffmpeg not found on PATH")`.

`run_analysis` calls `on_stage("decode" | "trim" | "beats" | "snap" | "tempo")` as it goes and wraps any failure in `StageError(stage, message)`, so the caller always knows where it broke. The beats stage also builds a rough tempo map from the raw beats and runs the octave check on each rough segment. The tempo stage builds the real tempo map from the snapped beats. With a previous report (re-analysis), its manual segments and edits carry over. Ingest isn't a job stage. It runs during the upload request, so a bad file is rejected with a 4xx straight away instead of becoming a failed job.

All times are milliseconds from the first decoded sample. Trim only reports boundaries and never cuts the audio, so later stages and the frontend share one timeline. Every segment's `anchor_ms` is on that timeline too (the first segment's is the first downbeat, no player compensation). The decode stage also reads the codec and the decoder padding with ffprobe, see `decisions.md`.

## server (`backend/api/`)

- `app.py`: `create_app(settings)` and the routes:
  - `POST /api/jobs`: upload, returns the job id.
  - `GET /api/jobs/{id}`: status.
  - `GET /api/jobs/{id}/report`: the timing report.
  - `GET /api/jobs`: every job, newest first. `?sha256=` narrows it to one file.
  - `PATCH /api/jobs/{id}/report`: one tempo edit, `{"op": "set_anchor" | "set_bpm" | "split" | "merge", ...}`, appends to `edits`.
  - `POST /api/jobs/{id}/reanalyze`: runs the analysis again, keeping manual segments and edits.
  - `GET /api/jobs/{id}/beats`: the beats file.
  - `GET /api/jobs/{id}/audio`: the decoded wav, for playback in the local UI.
  - `GET /api/health`.
- `jobs.py`: a `ThreadPoolExecutor` (one worker by default) runs `run_analysis` and writes status as stages change. On re-analysis it passes the old report in.
- `tempo_patch.py`: applies one tempo edit and writes the edit log entries for it.
- `storage.py`: job directories and atomic JSON writes.
- `settings.py`: data dir, upload limit, trim threshold, snap window, tempo range, worker count, all overridable with `STARSTEP_*` env vars.
- `python -m backend.api` starts uvicorn on 127.0.0.1:8000.

Job storage, one directory per job under `data/jobs/<job_id>/`:

```
original.<ext>   the upload as received
decoded.wav      ffmpeg output the analysis ran on
job.json         filename, sha256, size, created_at
status.json      {status, stage, error}, rewritten on every stage change
report.json      the timing report, once done
beats.json       every tracked beat (snapped and raw time, residual, bar), once done
```

Report edits go through one lock in `JobStore`, so a burst of patches can't read the same old report and drop an edit. Reports and beats files from schema 1.1 are upgraded to 2.0 as they're read (`backend/schema/migrate.py`).

Status and report are on disk, so a restart doesn't lose finished jobs. Jobs that were still queued or running when the server stopped are marked failed on the next start ("server restarted before the job finished"). There's no Celery, Redis, or database.

`status` is `queued | running | done | failed`. `stage` is `queued | decode | trim | beats | snap | tempo | done | failed`. A failure keeps the stage it happened in as `error.stage`.

## schema (`backend/schema/`, `shared/schema/`)

`models.py` is the source of truth for the timing report and the beats file (v2.0, see `schema-changelog.md`). `export_schema.py` writes `shared/schema/timing_report.schema.json` and `shared/schema/beats.schema.json`, which are committed. The frontend generates `frontend/src/types/timingReport.ts` and `frontend/src/types/beats.ts` from them with `npm run gen:types`.

Two checks keep them in sync. A pytest test fails if a committed JSON Schema differs from its model, and `npm run check:types` fails if the committed TypeScript differs from what the JSON Schemas generate.

Rules that hold from now on:

- Every tempo/meter/section segment has `source: "auto" | "manual"`. Re-analysis only replaces auto segments.
- `edits` is append-only and records every manual change.
- Beats go in their own file next to `report.json`, not inside the report.
- Breaking changes bump `schema_version` and get a changelog entry.

## frontend (`frontend/`)

Vite + React + TypeScript. In dev, Vite proxies `/api` to the backend, so there's no CORS setup.

- Upload goes through `XMLHttpRequest` because fetch can't report upload progress.
- `poll.ts` holds the polling loop as a plain async function with an injectable sleep.
- The page is laid out around the timeline. It's a full-width band at the top with the wavesurfer waveform, the tempo bands and the beat grid in it. Under it is a strip with the transport, the zoomed view and the segment controls, and then the source and report columns. The source column also lists recent jobs.
- The open job's id is in the url (`?job=`), so a reload reopens it. `jobs.ts` has the url and hashing helpers.
- `grid.ts` has the beat-to-pixel maths for one grid and `tempoMap.ts` puts the segments' grids together (boundaries, bar numbers across segments, bands). `tempoEdits.ts` is the edit logic (`EditSaver` debounces anchor nudges, sends everything else at once, and keeps one patch in flight). All three are plain modules with vitest tests, and the components only wire them up.
- `beatGridPlugin.ts` is the wavesurfer plugin that draws the bands and the grid, `components/Loupe.tsx` the zoomed view, `components/SegmentControl.tsx` the controls for the selected segment, and `components/Timeline.tsx` owns the wavesurfer instance.
- `fonts.ts` loads the Japanese font slices on demand.

## tests (`tests/`)

`synth.py` generates click tracks with known onsets, padding, an optional noise floor, accented downbeats, tempo changes, jitter and offbeat clicks. WAVs are cached in `tests/fixtures/` (git-ignored), keyed on a hash of the generator source and the spec. Tests that need ffmpeg carry `@pytest.mark.ffmpeg` and are skipped when it's missing.

## scripts (`scripts/`)

- `make_click_track.py` writes a click track for checking by hand, with tempo changes if asked.
- `eval_local.py` runs the pipeline on every song in a local folder and writes a csv of timing numbers, for tuning thresholds on real songs. It never writes audio.
- `check_madmom.py` checks a madmom install.
