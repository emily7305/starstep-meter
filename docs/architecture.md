# architecture

Three parts: a pure-Python analysis pipeline, a thin FastAPI server around it, and a React frontend. The pipeline doesn't know the server exists, so every stage can be run and tested from the command line.

## pipeline (`backend/analysis/`)

Each stage is a plain function that takes paths or numpy arrays and returns a small dataclass.

| module | in | out |
| --- | --- | --- |
| `ingest.py` | upload stream or file path, job dir | `IngestResult`: stored original, sha256, size, ffprobe info |
| `decode.py` | original file | `decoded.wav` (mono float32, native rate) and `DecodedAudio` |
| `trim.py` | samples, sample rate | `TrimResult`: `start_ms`, `end_ms`. Also `stretch_level`, the level of a stretch against the song's, for the tempo map's weak edge rule |
| `beats.py` | samples, sample rate, trim bounds, tempo range | `TrackedBeats`: beat times, positions in the bar, which tracker. Also madmom's measured bias |
| `octave.py` | samples, tracked beats, rough segments and their tempos | `TrackedBeats` doubled or halved per segment, and an `OctaveCheck` per segment |
| `snap.py` | samples, sample rate, beat times, bias shift | `SnapResult`: beat times moved onto onsets |
| `tempo_map.py` | snapped times, downbeat flags, trim bounds, a loudness lookup, an onset strength lookup | `TempoMapResult`: segments, each with its own `GridFit`, the felt sections folded into it and its off-beat runs |
| `grid_fit.py` | the snapped times of one segment | `GridFit`: period, anchor, indices, residuals, confidence |
| `tempo_edit.py` | tempo segments, tracked beat times | the manual edits (split, merge, match, bpm, anchor) and `keep_manual_segments` for re-analysis |
| `bars.py` | tempo map, meter map | bar lines and beat lines, the rule `frontend/src/tempoMap.ts` draws with too |
| `features.py` | samples, sample rate, grid positions | `GridFeatures`: low, mid and high band onset strengths at each position |
| `meter.py` | tempo map, snapped times, downbeat flags, an accent lookup | `MeterResult`: meter runs over the whole map, and the tempo map with each anchor on beat 1 |
| `notation.py` | tempo segments, meter runs, grid features | `Suggestion`s: half and double time feel spans, and folding an edge stretch into its neighbour |
| `swing.py` | samples, tempo segments, meter runs | `SwingSection`s: swing and gallop stretches, with the note division a chart needs for them |
| `meter_edit.py`, `notation_edit.py` | meter map, tempo map, suggestions | the meter edits (set, split, merge), applying a suggestion, and what re-analysis keeps |
| `tempo_range.py` | | `TempoRange`, the one bpm range every tempo path uses, 60–320 by default |
| `tempo.py` | samples, sample rate, trim bounds | `TempoResult`: milestone 1 bpm estimate, only used by the librosa fallback now |
| `pipeline.py` | original, work dir, filename, sha256, previous report | `AnalysisOutput` with the `TimingReport` and the `BeatsFile` |
| `cli.py` | file path | report JSON on stdout |
| `cross_check.py` | samples, trim bounds, the tempo map's beats and segments | `CrossCheck`: librosa's snapped beats compared with the main ones per segment, felt sections and off-beat runs left out |
| `confidence.py` | tempo map, snapped beats, cross-check | `Confidence`: one per segment and one per span of 16 grid beats, from the residuals and the agreement |
| `export.py` | report, beats file | the timing export as a dict, checked against `shared/schema/`. Also a CLI |

`ffmpeg_tools.py` finds and runs ffmpeg/ffprobe (`shutil.which`, argument lists, never a shell). A missing tool raises `ToolNotFoundError("ffmpeg not found on PATH")`.

`run_analysis` calls `on_stage("decode" | "trim" | "beats" | "snap" | "tempo" | "meter" | "check")` as it goes and wraps any failure in `StageError(stage, message)`, so the caller always knows where it broke. The beats stage also builds a rough tempo map from the raw beats, without the consolidation pass, and runs the octave check on each rough segment. A felt section only changes octave when it stays at a ratio of its neighbours. The tempo stage builds the real tempo map from the snapped beats: segmentation, then the consolidation pass that folds felt sections (in the middle, next to an intro or outro stub, or at the very edge), off-beat stretches, runs of short pieces, short pieces and weak edges into their neighbours, then the off-beat pass that marks where the tracker followed the off-beat and checks each grid's phase against the onsets. The meter stage first counts any bar positions the octave check counted per beat again on the grid, then reads the band strengths at every grid line and half line, infers the meter from the downbeats and the accents, works out the notation suggestions from the same band strengths, and reads where the notes sit between the grid lines for swing and gallop. The check stage runs librosa's tracker as a second opinion, compares it per tempo segment, and works out the confidence of each segment and of each span of it. With a previous report (re-analysis), its manual segments, manual meter, decided suggestions and edits carry over. Ingest isn't a job stage. It runs during the upload request, so a bad file is rejected with a 4xx straight away instead of becoming a failed job.

All times are milliseconds from the first decoded sample. Trim only reports boundaries and never cuts the audio, so later stages and the frontend share one timeline. Every segment's `anchor_ms` is on that timeline too (the first segment's is the first downbeat, no player compensation). The decode stage also reads the codec and the decoder padding with ffprobe, see `decisions.md`.

## server (`backend/api/`)

- `app.py`: `create_app(settings)` and the routes:
  - `POST /api/jobs`: upload, returns the job id.
  - `GET /api/jobs/{id}`: status, with `report_available` for a failed re-analysis that left the last good report.
  - `GET /api/jobs/{id}/report`: the timing report.
  - `GET /api/jobs`: every job, newest first, where a finished re-analysis counts as new (`reanalyzed_at`). `?sha256=` narrows it to one file.
  - `PATCH /api/jobs/{id}/report`: one edit, `{"op": "set_anchor" | "set_bpm" | "split" | "split_out" | "merge" | "match" | "set_meter" | "split_meter" | "merge_meter" | "apply_suggestion" | "dismiss_suggestion", ...}`, appends exactly one entry to `edits`.
  - `POST /api/jobs/{id}/reanalyze`: runs the analysis again, keeping manual segments and edits.
  - `GET /api/jobs/{id}/beats`: the beats file.
  - `GET /api/jobs/{id}/export`: the timing export as a download. `?beats=true` adds the beats file. Checked against `shared/schema/` before it's returned.
  - `DELETE /api/jobs/{id}`: deletes the job folder, not while it's queued or running.
  - `GET /api/jobs/{id}/audio`: the decoded wav, for playback in the local UI.
  - `GET /api/health`: ffmpeg and ffprobe found, madmom installed and importing (checked once at startup).
- `jobs.py`: a `ThreadPoolExecutor` (one worker by default) runs `run_analysis` and writes status as stages change. On re-analysis it passes the old report in and decodes into `.rerun/`, so a failed run leaves the job's files as they were.
- `tempo_patch.py`: applies one edit (tempo, meter or suggestion) and writes its one edit log entry.
- `storage.py`: job directories and atomic JSON writes.
- `settings.py`: data dir, upload limit, trim threshold, snap window, tempo range, worker count, retention, all overridable with `STARSTEP_*` env vars.
- `python -m backend.api` starts uvicorn on 127.0.0.1:8000.

Job storage, one directory per job under `data/jobs/<job_id>/`:

```
original.<ext>   the upload as received
decoded.wav      ffmpeg output the analysis ran on
job.json         filename, sha256, size, created_at, reanalyzed_at
status.json      {status, stage, error}, rewritten on every stage change
report.json      the timing report, once done
beats.json       every tracked beat (snapped and raw time, residual, bar), the band strengths at the grid and librosa's beats, once done
.rerun/          only while a re-analysis runs, its decoded wav until the run succeeds
```

Report edits go through one lock in `JobStore`, so a burst of patches can't read the same old report and drop an edit. Reports and beats files from schema 1.1, 2.0, 2.1, 2.2, 2.3 and 2.4 are upgraded to 2.5 as they're read (`backend/schema/migrate.py`).

Status and report are on disk, so a restart doesn't lose finished jobs. At startup, job folders unchanged for longer than the retention (14 days by default) are deleted, then jobs that were still queued are queued again, and jobs that were running are marked failed ("server restarted before the job finished"). There's no Celery, Redis, or database.

`status` is `queued | running | done | failed`. `stage` is `queued | decode | trim | beats | snap | tempo | meter | check | done | failed`. A failure keeps the stage it happened in as `error.stage`.

## schema (`backend/schema/`, `shared/schema/`)

`models.py` is the source of truth for the timing report and the beats file (v2.5, see `schema-changelog.md`), and `export_models.py` for the export file. `export_schema.py` writes `shared/schema/timing_report.schema.json`, `beats.schema.json` and `timing_export.schema.json`, which are committed. The frontend generates one TypeScript file per schema in `frontend/src/types/` with `npm run gen:types`. `validate.py` checks a document against a committed schema file with jsonschema, which the exports go through.

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
- Before a song is open the page is a drop zone where the timeline goes, with the recent jobs beside it (`components/UploadPanel.tsx` in its start form). A song can be dropped anywhere on the page, `fileDrop.ts` has the checks. With a report, the page is laid out around the timeline: the plain answer card, then a full-width band with the wavesurfer waveform, the tempo bands and the beat grid, an overview strip above it, then a strip with the transport, the zoomed view with the meter control and the suggestions under it, and the segment control, then the chart setup panel, and the source, recent and report columns across the bottom. A footer with the credits closes every page.
- The open job's id is in the url (`?job=`), so a reload reopens it. `jobs.ts` has the url and hashing helpers.
- `timelineNav.ts` has the scrolling and zooming maths for the big timeline: the speed a drag held near an edge scrolls at, wheel deltas, zoom around a point, the visible window. `components/Timeline.tsx` drives the drag itself with a frame loop (wavesurfer's own drag-to-seek is off), and `components/Overview.tsx` draws the whole song with the visible window on it.
- `grid.ts` has the beat-to-pixel maths for one grid and `tempoMap.ts` puts the segments' grids together (boundaries, bar lines from the meter map with the backend's rule, bar numbers across segments, bands). `tempoEdits.ts` is the edit logic (`EditSaver` debounces anchor nudges, sends everything else at once, and keeps one patch in flight). All three are plain modules with vitest tests, and the components only wire them up.
- `beatGridPlugin.ts` is the wavesurfer plugin that draws the bands, the grid, a thin mark for each open suggestion, a label at each bpm and time signature change and the low confidence shading, `components/Loupe.tsx` the zoomed view, `components/SegmentControl.tsx` the controls for the selected segment, `components/MeterControl.tsx` the ones for the meter under the zoomed view, `components/SuggestionList.tsx` the suggestions with apply and dismiss, and `components/Timeline.tsx` owns the wavesurfer instance.
- `chartSetup.ts` turns the bar lines and the tempo map into what a chart editor needs, the offset and the changes by measure and beat, and `components/ChartSetup.tsx` is the panel that shows and copies it.
- `quickAnswer.ts` and `components/QuickAnswer.tsx` are the plain answer above the timeline (bpm, the two offsets, time signature), built from the chart setup list.
- `subdivisions.ts` names the swing and gallop sections and works out the division they need at the bpm their segment has now. `components/SuggestionList.tsx` lists them under the notation suggestions, and `chartSetup.ts` (`feelLines`) gives the panel's line per section by measure.
- `tour.ts` and `components/Tour.tsx` are the first-visit tour, five steps pointing at elements marked `data-tour`, shown once per browser and opened again from the `?` in the header.
- `wav.ts` reads the decoded wav at its own sample rate for the zoomed view.
- `fonts.ts` loads the Japanese font slices on demand.
- `clockPlayer.ts` plays the decoded wav on an AudioContext the app owns and is wavesurfer's media element. Its playhead time trails the rendered audio by the output latency the browser reports, and it keeps the wav's own samples for the zoomed view. `clickTrack.ts` puts a click on every beat line and an accented one on every bar line, started at exact times on that context. Both have vitest tests with a fake context.
- `components/ExportPanel.tsx` is the export block in the source column, with `exportOptions.ts` for the request, and `editLog.ts` reads an edit log entry for the report column.

## tests (`tests/`)

`synth.py` generates click tracks with known onsets, padding, an optional noise floor, accented downbeats, tempo changes, jitter, offbeat clicks, sections where the clicks play another rhythm over the same tempo (dotted, triplet feel) and meter changes. It also makes drum tracks (kick, snare, hats) with half and double time feel sections on a steady pulse. WAVs are cached in `tests/fixtures/` (git-ignored), keyed on a hash of the generator source and the spec. Tests that need ffmpeg carry `@pytest.mark.ffmpeg` and are skipped when it's missing.

`tests/real/<song>/` (git-ignored) holds the beats file and report of real songs, timing data only. `test_real_song.py` runs the tempo map on each and skips a song that isn't there, and runs the notation suggestions again from the band strengths in the beats file when it has them.

## scripts (`scripts/`)

- `make_click_track.py` writes a click track for checking by hand, with tempo changes, felt rhythm sections and ticks between the beats (swing, gallop) if asked.
- `eval_local.py` runs the pipeline on every song in a local folder and writes a csv of timing numbers (meter and notation suggestions included), for tuning thresholds on real songs. It never writes audio.
- `check_madmom.py` checks a madmom install.
