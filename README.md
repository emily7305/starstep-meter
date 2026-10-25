# starstep-meter

Beat, tempo, and meter analysis for rhythm game charting. Personal project.

*✦ star steps, right on the beat ✦*

Milestone 3 runs on your own machine, and adds tempo maps to the beat tracking of milestone 2. You upload a song in the browser, and the backend decodes it with ffmpeg, finds where the music starts and ends (the trim), and tracks beats and downbeats with madmom, or with a librosa fallback when madmom isn't installed. A check for half or double tempo runs on the tracked beats, and every tempo path searches 60 to 320 bpm by default. Each tracked beat is snapped onto the nearest onset, and the snapped beats are split into tempo segments. Each segment gets its own bpm and its own anchor, the time of its first downbeat, from a linear fit through its beats, so the first downbeat of the song is `tempo_map[0].anchor_ms`. The beats are written to their own file next to the report. The browser shows a waveform timeline with the segments as bands and the beat grid on them, and a zoomed view for checking the grid against an attack. A segment can be split, merged with a neighbour, given an exact bpm, doubled or halved, and have its anchor moved in 1 ms steps, with every edit recorded in the report's `edits`. A job reopens from the url or from the recent list, and picking a file that was analyzed before offers to reopen it. The report also records the codec and the decoder padding of the source file. A CLI does the same analysis for one file.

Milestone 4 adds meter and notation suggestions. The analysis infers the meter (beats per bar) of each tempo segment from madmom's downbeats, and the accents get a say where they are clearly stronger than the other beats of a bar. Bar lines are drawn from the meter map, and a meter can be set by hand per region. It also suggests where a chart may write the pulse at half or twice the tempo (a half or double time feel, read from the kick and snare bands), and where a first or last stretch of the song may be its neighbour's tempo (a fold). Suggestions are never applied automatically. Each one can be applied, as one edit (a half or double time feel leaves every grid line where it is), or dismissed, and both stay through re-analysis.

Milestone 5 adds export and a way to check the grid by ear. The timing JSON downloads from the browser, with the beats file if asked for, and is checked against the JSON Schema in `shared/schema/` before it goes out. A Sonolus preset gives the values a Sonolus level needs (the bgm offset in seconds, the bpm changes and the time signatures), with a decoder compensation setting for a player that decodes the audio differently from ffmpeg. A click track plays a click on every beat and an accented one on every bar line, on the same audio clock as the song. Every manual change is one entry in the edit log. Old jobs are deleted after 14 days without a change, one job can be deleted by hand, and a job still waiting in the queue when the server stops runs when it starts again.

Milestone 6 adds a second opinion on the beats, a confidence for the tempo map, and a list for setting up a chart. librosa's beat tracker runs as a cross-check next to madmom and flags the tempo segments where the two disagree by more than a configurable number of ms (felt sections and off-beat runs are left out, since the grid deliberately doesn't follow the tracker there). Every tempo segment and every stretch of 16 grid beats gets a confidence from the fit residuals and that agreement, and the low ones are shaded on the timeline. A chart setup panel lists the music offset and every bpm and time signature change by measure, for typing into a chart editor (MikuMikuWorld was the one checked). The zoomed view draws the wav at its own sample rate, and the playhead is drawn behind the sound by the output latency the browser reports. Jobs can be deleted from the recent list.

It does not find sections yet. The tempo map and the meter are tuned on synthetic tracks and a handful of real songs. The half and double time suggestions found nothing on the three real songs checked so far, whose drums show no plain backbeat to read (see `docs/decisions.md`), so on a real song check the bands, the bar lines and the suggestions, and fix them by hand where they are wrong. This is for personal use only. The server binds to 127.0.0.1, there are no accounts or sharing, and exports contain timing data only, never audio. Uploaded audio is kept only in the local `data/` folder.

## Dependencies and licenses

This project's code is licensed under PolyForm Noncommercial 1.0.0 (see `LICENSE`), so it is for noncommercial use only.

madmom is used for beat and downbeat tracking when it's installed. Without it, the librosa fallback runs with lower confidence and a guessed downbeat. madmom's code is BSD-licensed, and its pretrained models carry their own CC BY-NC-SA 4.0 terms. This project does not redistribute madmom or its models. Whoever runs the tool installs them separately.

The licenses below were read from the installed packages' own metadata (Python `importlib.metadata`, npm `package.json`) on 2026-10-25.

### Python runtime

| Package | Version | License | Notes |
|---|---|---|---|
| fastapi | 0.162.0 | MIT | |
| pydantic | 2.14.1 | MIT | |
| uvicorn | 0.54.0 | BSD-3-Clause | |
| numpy | 2.4.6 | BSD-3-Clause | Bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |
| soundfile | 0.14.0 | BSD-3-Clause | Wheels bundle libsndfile, which is LGPL-2.1 |
| librosa | 0.11.0 | ISC | |
| python-multipart | 0.0.32 | Apache-2.0 | |
| jsonschema | 4.26.0 | MIT | Checks every export against the committed JSON Schema before it goes out |

### Pulled in by librosa

These come in through librosa. soxr is LGPL-2.1-or-later, so it is the one to watch.

| Package | Version | License |
|---|---|---|
| scipy | 1.17.1 | BSD-3-Clause |
| numba | 0.68.0 | BSD-2-Clause |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| soxr | 1.1.0 | LGPL-2.1-or-later |

### Pulled in by jsonschema

These come in through jsonschema.

| Package | Version | License |
|---|---|---|
| attrs | 26.1.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.9.1 | MIT |

### Python dev and test

| Package | Version | License |
|---|---|---|
| pytest | 9.1.1 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |

### Optional: madmom

| Package | Version | License | Notes |
|---|---|---|---|
| madmom | 0.17.dev0, git commit 27f032e | BSD (code), CC BY-NC-SA 4.0 (pretrained models) | Installed with the `madmom` extra only |

### npm runtime

| Package | Version | License |
|---|---|---|
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| `@fontsource/m-plus-rounded-1c` | 5.3.0 | OFL-1.1 |
| `@fontsource/ibm-plex-mono` | 5.3.0 | OFL-1.1 |
| wavesurfer.js | 7.12.12 | BSD-3-Clause |

### npm dev

| Package | Version | License |
|---|---|---|
| typescript | 7.0.2 | Apache-2.0 |
| vite | 8.3.5 | MIT |
| `@vitejs/plugin-react` | 6.1.2 | MIT |
| vitest | 5.0.5 | MIT |
| `@types/react` | 19.3.0 | MIT |
| `@types/react-dom` | 19.3.0 | MIT |
| json-schema-to-typescript | 16.0.0 | MIT |

### External tools, not installed by this project

| Tool | License | Notes |
|---|---|---|
| ffmpeg, ffprobe | LGPL-2.1+ or GPL, depending on the build | The common Windows and Ubuntu builds are GPL |

Versions are what was installed when checked. `pyproject.toml` and `package.json` allow newer ones.

## Install on Windows

Windows is the main machine for this project.

### Python

Install Python 3.11 with the `py` launcher, either from python.org or with `winget install Python.Python.3.11`. Then, from the repo root, create a virtual environment and activate it:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

PowerShell may refuse to run scripts. If it does, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. In cmd, activate with `.venv\Scripts\activate.bat` instead.

Install the project with the dev extras:

```powershell
python -m pip install -e ".[dev]"
```

### ffmpeg

Install it with `winget install Gyan.FFmpeg`, then open a new terminal so PATH picks it up. Check both tools:

```powershell
ffmpeg -version
ffprobe -version
```

The manual alternative is to download a release build from gyan.dev and unzip it somewhere like `C:\tools\ffmpeg`. Add `C:\tools\ffmpeg\bin` to the user PATH (Settings → System → About → Advanced system settings → Environment Variables), then open a new terminal.

If ffmpeg is missing, the server still starts. `/api/health` and the header in the UI say so, and jobs fail at decode with "ffmpeg not found on PATH".

### Node

Node 22.12 or newer is needed, because vitest 5 requires it. Install the LTS release with `winget install OpenJS.NodeJS.LTS`, open a new terminal, and check `node --version`. Then install the frontend packages:

```powershell
cd frontend
npm install
```

### madmom (optional)

Without madmom, beat tracking falls back to librosa, with lower confidence and a guessed downbeat. An install that is present but fails to import falls back the same way, and `--tracker madmom` turns either case into an error. To install it:

```powershell
python -m pip install -e ".[madmom]"
```

madmom installs from a pinned git commit, because the PyPI release (0.16.1) does not build or import on current Python and numpy. The details are in `docs/decisions.md`. You need Git on PATH. madmom compiles Cython extensions, so you also need the Microsoft C++ Build Tools with the "Desktop development with C++" workload.

Check the install with:

```powershell
python scripts\check_madmom.py
```

This has not been tested on Windows yet. It worked on Linux with Python 3.11.

## Install on Linux

```bash
sudo apt install ffmpeg python3.11 python3.11-venv
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Any Python 3.11 or newer works. If you use a newer one, replace `python3.11` in the commands above.

Node needs to be 22.12 or newer. Ubuntu's apt `nodejs` is usually too old, so install Node from nodesource or with nvm. Then install the frontend packages:

```bash
cd frontend
npm install
```

madmom is the same as on Windows, except the build tools are a C compiler (`sudo apt install build-essential`). It still installs from git, so Git must be installed.

## Running

The backend is `python -m backend.api`. It serves on http://127.0.0.1:8000 and is only reachable from this machine. Use `--port` to change the port. There is also a `--host` option, but any value other than localhost prints a warning, and it is not meant for normal use.

```bash
python -m backend.api
```

In a second terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open http://127.0.0.1:5173 in the browser. Vite proxies `/api` to the backend, so both need to be running.

After a job finishes, the timeline shows the waveform with the beat grid and the tempo segments as bands. Each band has a label along the bottom, like `200.00 bpm · manual`. Clicking the waveform selects the tempo segment under the click (in a song with more than one segment, its band gets the pink accent) and puts the nearest tracked beat in the zoomed view. The controls on the right act on that segment:

- The bpm has ÷2, ×2, ×3/4, ×4/3, ×2/3 and ×3/2 buttons, and a field with a "set bpm" button for an exact value. They keep the anchor and rebuild the grid from it. The 60–320 bpm range is only for detection, a value set here can go up to 1000.
- The anchor moves in 1 ms steps with the −1 ms and +1 ms buttons, and with ← and → while the timeline has focus. A change is saved about half a second after the last step.
- "anchor here" rebuilds the grid from the tracked beat in the zoomed view, and "split here" splits the segment at that beat.
- "merge ←" and "merge →" merge the segment with the one before it or after it.
- "match previous" and "match next" join the segment to its neighbour with the neighbour's bpm and anchor, as one edit. That's for a stretch that is the same tempo felt differently.
- When the analysis kept a felt section (a dotted or triplet rhythm) on the segment's grid, the panel lists it under "kept on this grid" with its own bpm and ratio, like `203.36 bpm (3/4)`. "split out" splits at both its ends, so it gets its own tempo back. The report's tempo map list shows the same sections.
- Where the beat tracker followed the off-beat for a while, the timeline hatches that stretch and the panel lists it under "off-beat runs" with its start, end and beat count. The grid stays on the beats there.

Stretches the analysis is less sure of are shaded on the timeline: a darker wash with a dotted edge along the bottom and a "low confidence" label. Each is a span of 16 grid beats whose confidence is under 0.5. The confidence comes from how many beats sit within 10 ms of the grid and how well librosa's beats agree, and the formula is in `docs/decisions.md` (confidence, milestone 6). Only spans under auto segments are shaded, because the spans were measured on the analysis' grid and a segment set by hand has a different one.

Each tempo or time signature change after the first gets a label on the timeline at its bar line, like `m.24 · 150.00 bpm` or `m.37 · 3/4`. One label shows both when they share a line, and when zoomed out a label that would run into the one before it is left out. The numbers are the bar numbers along the top, which start at 0 on the first bar line in the audio, not on the first downbeat. With a lead-in shorter than a bar those are the same line. With a longer intro the first downbeat gets a later number.

Under the notation suggestions is the chart setup panel, with the music offset and every bpm and time signature change by measure. "Setting up a chart from the list" below goes through it.

Under the play time, a line says how far behind the audio the playhead is drawn, like `playhead −42.0 ms output latency`. It is the output latency and base latency the browser reports, and it is read again as the device changes. Only the drawing moves, the music and the clicks are not. When the browser reports no output latency, the line says the playhead isn't compensated. On Bluetooth the reported number may still be off.

Every change shows up in the report's edits list. Splitting or merging a segment that the analysis fitted refits it from the tracked beats, while a segment whose bpm or anchor was set by hand keeps its grid.

If a re-analysis fails, the last good report stays on screen with a note saying at which stage the re-analysis failed. The header says `madmom failed to import` when madmom is installed but doesn't import, with the error in its tooltip.

The url carries the job id (`?job=...`), so a reload reopens the job with its edits. The source column lists recent jobs, newest first, and any of them can be reopened. Picking a file that was analyzed before and pressing analyze offers to reopen it first, with "reopen" for each earlier job and "analyze again as a new job" to start over. The "re-analyze" button runs the analysis again on the stored upload and keeps the manual segments and the edit log.

Under the zoomed view is the meter panel. It acts on the meter segment at the beat in the zoomed view, and its heading says which one, like "meter 1 of 2". The numerator and denominator fields with the "set meter" button set that segment's meter by hand. "split meter here" starts a new meter at the beat in the zoomed view, and the bars restart there. "merge ←" and "merge →" merge the segment with the one before it or after it. A bar is numerator × 4 / denominator beats of the grid, so 7/8 is three and a half beats. The bar lines on the timeline come from the meter map.

Under the detail strip is the "notation suggestions" list. Each open suggestion shows its kind ("half time", "double time" or "fold into neighbour"), its start and end, the suggested bpm with the bpm it was made on, and a score from 0 to 1. Selecting one moves the playhead and the zoomed view to its start and highlights its mark on the timeline. "apply" and "dismiss" decide it, and the decided ones are counted in one line, like `1 applied, 2 dismissed`. The thin marks along the top of the timeline, under the bar numbers, are the open suggestions.

Applying a half or double time suggestion splits the segment at both ends of the span, on bar lines, and sets the span to half or twice its bpm, so the bars there are twice or half as long, and every grid line stays where it is. A fold puts the stretch on its neighbour's grid, the way "match previous" and "match next" do. Applying is one edit, and dismissing only logs the status.

"click track" next to play turns the click track on and off. It clicks on every beat line of the grid and plays a higher, louder click on every bar line, so it follows the tempo map, the meter and an anchor while it's being nudged. The clicks are scheduled on the same audio clock as the song, so they stay with it however long it plays. On Bluetooth headphones the sound comes out later than the playhead moves, the clicks and the song together, so watch the playhead on wired output (see "click track" in `docs/decisions.md`).

Each edit in the report's edits list is one manual change. When one change touched several values, like the first ×2 on an auto segment (the bpm, plus the switch to manual and the dropped confidence), the entry has a line for each.

The export block in the source column downloads the JSON. "timing json" is the report as it is, and "include beats.json" adds the beats file. "sonolus" gives the values for a Sonolus level instead, see "Sonolus export" below. The file is named after the song, like `song.timing.json` or `song.sonolus.json`. The last choice is remembered in the browser.

Each job in the recent list has a delete button. It asks "delete this job and its files?" first, and deletes only on the second press, upload and decoded wav included. The button is not shown for a job that is queued or running, and the server refuses to delete one. The same can be done from the command line with the job id from the url:

```bash
curl -X DELETE http://127.0.0.1:8000/api/jobs/<job id>
```

### Settings

Settings come from environment variables. Set them in the terminal before you start the backend. In PowerShell:

```powershell
$env:STARSTEP_MAX_UPLOAD_MB = "200"
python -m backend.api
```

In bash:

```bash
export STARSTEP_MAX_UPLOAD_MB=200
python -m backend.api
```

| Variable | Default | What it does |
|---|---|---|
| `STARSTEP_DATA_DIR` | `data/` in the repo | Where uploads and job files are stored |
| `STARSTEP_MAX_UPLOAD_MB` | 100 | Largest upload accepted, in MB |
| `STARSTEP_TRIM_THRESHOLD_DB` | -60 | Trim threshold in dB, relative to the loudest 20 ms frame |
| `STARSTEP_SNAP_WINDOW_MS` | 20 | How far, in ms, onset snap may move a tracked beat |
| `STARSTEP_MIN_BPM` | 60 | The slowest tempo, in bpm, that any tempo path considers |
| `STARSTEP_MAX_BPM` | 320 | The fastest tempo, in bpm, that any tempo path considers |
| `STARSTEP_CROSS_CHECK_MS` | 20 | Flags a tempo segment where madmom and librosa's beats are further apart than this, in ms |
| `STARSTEP_WORKERS` | 1 | Number of analysis workers |
| `STARSTEP_RETENTION_DAYS` | 14 | Job folders that haven't changed for this many days are deleted at startup, 0 keeps them |

### CLI without the server

The CLI runs the same analysis on one file and prints the report JSON:

```powershell
python -m backend.analysis.cli path\to\song.mp3 -v
```

With `-v`, stage progress and debug numbers go to stderr, including the `beats` line (the tracker and how many beats it found), the `octave` lines (one per rough tempo segment: what the half or double check did, the tracked bpm, and the midpoint and parity ratios it decides on), the `snap` line (how many beats snapped to an onset, the bias shift applied to madmom's beats before the search, and the median move) and the `tempo` line (the number of segments, the residual rms, the outliers and the confidence), followed by one `[i]` line per segment with its start and end, bpm, anchor and beat count. `-v` also prints a `meter` line (how many meter segments and how many grid positions were read) with one `[i]` line per meter segment (start, end, numerator/denominator and confidence), and one `suggest` line per suggestion (kind, start and end, the suggested bpm and the bpm it was made on, and the score). The `check` line gives the librosa cross-check: how many beats librosa found and the distance above which a segment is flagged, with one `[i]` line per tempo segment saying the median distance between the two trackers' beats, how many beats were compared, and `flagged` when it is over the limit (or `too few beats to compare`). When librosa is the main tracker, the `check` line says there is no cross-check. The `conf` line lists the confidence of each tempo segment and how many of the 16 beat spans are low, followed by one `low` line per low span with its start and end and its confidence. `--threshold-db` sets the trim threshold. `--tracker auto|madmom|librosa` picks the beat tracker. `auto`, the default, uses madmom when it's installed and falls back to librosa otherwise, `madmom` is an error if madmom is missing or fails to import, and `librosa` skips madmom. `--snap-window-ms` sets how far onset snap may move a tracked beat, 20 ms by default. `--cross-check-ms` sets how far apart madmom's and librosa's beats may be in a tempo segment before it is flagged, 20 ms by default. `--min-bpm` and `--max-bpm` set the slowest and fastest tempo any tempo path considers, 60 and 320 by default. `--beats PATH` also writes the beats file to PATH, and the report still goes to stdout. `--work-dir` keeps the copied original and the decoded WAV in a folder you choose instead of a temp dir.

### Storage

Each job keeps a copy of the upload, the decoded WAV, and `beats.json` (every tracked beat, with its raw and snapped time) under `data/jobs/<job id>/`. `beats.json` also holds the band strengths (low, mid and high) at every grid line and half line. They are timing numbers only, and they let the suggestions be checked again without the audio. It also holds librosa's snapped beats (`cross_check_beats`), also timing only, so the cross-check and the confidence can be worked out again without the audio. The decoded WAV is mono float32, about 10 MB per minute at 44.1 kHz. When the server starts, it deletes job folders that haven't changed for 14 days (`STARSTEP_RETENTION_DAYS`). A change is the upload, an analysis or re-analysis, or an edit, so a job you're still editing stays, and one you only open or export doesn't count as changed. `data/` is git-ignored.

A job that was still waiting in the queue when the server stopped runs when it starts again. One that was in the middle of its analysis is marked failed instead ("server restarted before the job finished"), and "re-analyze" runs it again.

## Real songs: eval_local.py

The thresholds for the trim, the onset snap, the half or double check and the tempo map are tuned on synthetic tracks only. `scripts/eval_local.py` runs the same analysis on a folder of your own songs and writes a csv of timing numbers, one row per song, to paste into a later session for tuning them on real music. It needs ffmpeg and ffprobe on PATH, and it looks for mp3, wav, flac, ogg and m4a files.

In PowerShell:

```powershell
python scripts\eval_local.py C:\path\to\songs --recursive --tracker madmom --out results\songs.csv
```

In bash:

```bash
python scripts/eval_local.py ~/path/to/songs --recursive --tracker madmom --out results/songs.csv
```

`--recursive` also looks in subfolders. `--tracker auto|madmom|librosa` works as in the CLI. `--min-bpm` and `--max-bpm` set the tempo range, 60 and 320 by default. `--cross-check-ms` sets the distance above which a tempo segment is flagged by the librosa cross-check, 20 ms by default. `--out` is the csv to write. It defaults to `eval_local.csv` in the current directory, and nothing is written next to the songs. Progress goes to stderr, one line per song, and the last line says how many files failed.

The csv has timing data only, never audio. The decoded WAV of a song exists only in a temp folder while that song is analyzed. Error messages have absolute paths replaced: the song folder by `<folder>`, the temp folder by `<tmp>` and the home folder by `~`. The file names of the songs are in the csv, as paths relative to the folder, so read it before you share it.

The columns:

- `file`, `duration_ms`, `codec`, `sample_rate` and `tracker` say which song the row is, how long it is, how it was encoded, and which beat tracker ran.
- `octave` is what the half or double check did over the song: `kept`, `doubled`, `halved` or `mixed`.
- `segments` is the number of tempo segments, and `segment_starts_ms`, `segment_bpms` and `segment_confidences` list each segment's start, bpm and confidence in order, separated by spaces. The confidence is the milestone 6 one, worked out from the fit residuals and the cross-check agreement (see `docs/decisions.md`), and halved for the librosa fallback.
- `residual_rms_ms` is the rms distance in ms of the beats that fit their grids, and `residual_p95_ms` and `residual_max_ms` are the 95th percentile and the largest distance over all beats, each measured from the grid of the beat's own segment. A beat in a felt section or an off-beat run is measured from the subdivision it sits on.
- `outliers` is the number of beats that were too far from their grid to count as fitting it.
- `confidence` is the share of all beats within 10 ms of their grid, halved for the librosa fallback.
- `ratio_merged` lists the felt sections kept on their segment's grid, like `3/4:44511-58724` (the ratio, then start and end in ms), and `offbeat_runs` the stretches where the tracker followed the off-beat, like `48664-52872`. Both are separated by spaces and empty when there are none.
- `meter` lists the meter segments, like `4/4:97 7/4:27948` (the signature, then start in ms), and `notation_suggestions` the suggestions, like `half:97-37020:0.62` (the kind, start and end in ms, then the score). Both are separated by spaces and empty when there are none.
- `cross_check_ms` has one value per tempo segment, separated by spaces: the median distance in ms between madmom's and librosa's beats. A `-` means there were too few beats to compare, and a `!` after the number means the segment was flagged. It is empty when there was no cross-check.
- `low_confidence` lists the spans of 16 grid beats with a confidence under 0.5 as `start-end:confidence`, with start and end in ms, separated by spaces and empty when there are none.
- `beats`, `beats_snapped` and `beats_not_snapped` are how many beats the tracker found and how many did and did not find an onset inside the snap window.
- `median_snap_move_ms` is the median distance in ms that a beat moved from the tracker's output to where it snapped, including the 11.8 ms bias shift for madmom. It is the real-song check of madmom's −11.8 ms bias. If the bias holds, the value comes out close to 11 ms (the shift, less the 0.7 ms or so by which snapped beats land before the attack), and a value far from that means the bias needs measuring again on real songs.
- `error` is empty for a song that worked, and otherwise holds a one-line message.

A song that fails gets a row with only `file` and `error` filled in, and the run carries on with the next song.

## Tests

Backend tests run from the repo root:

```bash
python -m pytest
python -m backend.schema.export_schema --check
```

Tests that need ffmpeg are skipped, not failed, when it is missing, and the madmom tests are skipped when madmom isn't installed. The tempo map tests run on synthetic beat lists and click tracks with known change points and felt rhythm sections. The meter and notation tests run on click tracks with meter changes and on generated drum tracks with half and double time sections. `tests/test_cross_check.py` and `tests/test_confidence.py` run on beat lists, and the confidence tests also on click tracks with a messy section, felt sections and an off-beat section. Test audio is generated in code and cached in `tests/fixtures/`, which is git-ignored.

`tests/test_real_song.py` checks the tempo map on real songs' `beats.json` and `report.json`, one folder per song under `tests/real/` (for example `tests/real/endymion/`). That folder is git-ignored, it holds timing data only, and a song's tests skip when its folder is missing. The test also runs the notation suggestions again from `beats.json`, and skips that part for a song whose beats file has no band strengths, which is any song analyzed before milestone 4. It also checks the confidence on the real songs: no low confidence on MisoilePunch♪'s felt sections or on YOUNITHM's off-beat runs. Those checks run without the cross-check, because the stored beats files are from before it. To refresh a song, analyze it again and copy `beats.json` and `report.json` from `data/jobs/<job id>/` into `tests/real/<song>/`.

Frontend checks run from `frontend`:

```bash
cd frontend
npm test
npm run check:types
npm run build
```

The frontend tests cover the beat-to-pixel mapping, the tempo map grid with the bar lines from the meter map, the edit queue, the suggestion helpers, the job url helpers, the edit log rows, the export options, the chart setup list, the wav reader, the playhead latency, and the click track and player on a fake audio context.

When you change `backend/schema/models.py` or `backend/schema/export_models.py`:

1. Run `python -m backend.schema.export_schema`. It writes every schema in `shared/schema/`: the report, the beats file and the two exports.
2. In `frontend`, run `npm run gen:types`. It regenerates one TypeScript file per schema in `frontend/src/types/`.
3. Add a line to `docs/schema-changelog.md`. Bump `schema_version` for breaking changes.

## Milestone 1 manual check

Generate a 120 BPM click track with 2 seconds of leading silence:

```bash
python scripts/make_click_track.py click-120.wav --bpm 120 --lead 2
```

The script prints the ground truth. The first click is at 2000.0 ms, and the last click ends at 21530.0 ms.

Start the backend and the frontend as described in Running, upload `click-120.wav`, and wait for the job to finish. Expected: trim start about 2000 ms (within a millisecond or so on WAV), trim end about 21530 ms, and BPM about 120.00.

Optionally, convert the file to MP3 and upload that as well:

```bash
ffmpeg -i click-120.wav -b:a 192k click-120.mp3
```

From the MP3, trim start comes out about 1 ms early because of MP3 pre-echo. BPM is the same.

The same check without the UI:

```bash
python -m backend.analysis.cli click-120.wav
```

Don't commit the generated audio. `*.wav` and `*.mp3` are git-ignored anyway.

## Milestone 2 listening check

Since milestone 3 the offset below is the first segment's anchor (`tempo_map[0].anchor_ms`, which replaced `beat_offset_ms`), so its steps are the −1 ms and +1 ms buttons under the segment controls, and the edits list names the field `tempo_map/0/anchor_ms`.

The expected values below are for madmom. With the librosa fallback the confidence is halved and the downbeat is a guess.

Generate a 120 BPM click track with accented downbeats and an offset that isn't a round number:

```bash
python scripts/make_click_track.py click-137.wav --bpm 120 --lead 0.1375 --accent
```

The first click, which is a downbeat, is at 137.506 ms and not 137.5, because the generator rounds to whole samples.

First the CLI check:

```bash
python -m backend.analysis.cli click-137.wav -v
```

Expected: `beat_offset_ms` about 136.77, and bpm 120.0 with confidence 1.0. Onset snap lands about 0.7 ms before a click's first sample on these clicks (see `docs/decisions.md`), which is why the offset is a little under 137.506. The test tolerance is 5 ms. With `-v`, the snap line shows a median move of about +7 ms, which is madmom's early bias being removed.

Then the UI check. Start the backend and the frontend as described in Running, upload `click-137.wav`, and wait for the job to finish.

1. The mint bar lines should sit on every 4th click, the louder, higher ones, with thinner beat lines on the others.
2. Press play and listen. Each accented click should sound exactly as the playhead crosses a bar line.
3. In the zoomed view at 40 ms wide, the grid line should sit on the attack, and the readout shows the grid within about ±0.05 ms of the tracked beat.
4. With the timeline focused, press → three times. The offset reads 139.774 ms (from 136.774 ms). After about half a second "saved" appears, and the edits list shows `136.774 ms → 139.774 ms`.
5. Confirm on the server with `curl http://127.0.0.1:8000/api/jobs/<job id>/report`. The job id is the folder name under `data/jobs/`. The report there should show the same offset and the same edit.
6. Press ← three times to go back. That is a second edit, and the log keeps both.

Next the MP3 check. Convert the file and upload that as well:

```bash
ffmpeg -i click-137.wav -b:a 192k click-137.mp3
```

The decoder padding row shows 1105 samples (25.057 ms), and the beat offset stays about 136.8 ms, because ffmpeg honours the LAME gapless header. A player that ignores that header would play this MP3 about 25 ms late. That correction is for export later, and it is not part of `beat_offset_ms`.

For the Japanese title check, copy the WAV to a Japanese name and upload it:

```bash
cp click-137.wav "テスト曲 120.wav"
```

The name should show in the rounded face (M PLUS Rounded 1c) in the timeline, the picker and the report, not in a system font.

Last, try a real song. Play from a few bars in and watch whether the bar lines land on the kick or snare you hear. If they drift across the song, it isn't one steady tempo. Since milestone 3 that shows up as more than one tempo segment, see the milestone 3 check below.

Don't commit the generated audio.

## Milestone 3 listening check

The expected values below are for madmom. The librosa fallback tracks at one tempo, so it can't follow the change in this track.

Generate a track that runs at 150 bpm and changes to 200 bpm, with accented downbeats:

```bash
python scripts/make_click_track.py tempo-check.wav --bpm 150 --beats 128 --lead 0.75 --accent --change 64:200
```

`--change 64:200` means click 64, counted from 0, is the first one at 200 bpm. The script prints the change at 26350.000 ms and the first click at 750.000 ms.

First the CLI check:

```bash
python -m backend.analysis.cli tempo-check.wav -v
```

Expected: two segments, 150.00 bpm and then 200.00 bpm. The `tempo` line says 2 segments and there are two `[i]` lines. The second segment starts at about 26349.3 ms, because onset snap lands about 0.7 ms before a click, as in milestone 2, and the first downbeat (`tempo_map[0].anchor_ms`) is at about 749.3 ms.

Then the UI check. Start the backend and the frontend as described in Running, upload `tempo-check.wav`, and wait for the job to finish. The timeline should show two bands, labelled 150.00 bpm and 200.00 bpm, and the tempo map list in the report should show the same two segments, both auto.

1. Click into the second band. It gets the pink accent, and the controls on the right now show segment 2 of 2.
2. Press ×2. The band's label reads 400.00 bpm · manual, and the edits list shows `tempo_map/1/bpm` as 200 bpm → 400 bpm (the fitted value can differ from 200 in the fourth decimal), plus a `source` entry (auto → manual) and a `confidence` entry that ends at –.
3. Press ÷2 to go back. The label reads 200.00 bpm · manual again, and the edits list gets one more `tempo_map/1/bpm` entry, 400 bpm → 200 bpm.
4. Click the second band again so the timeline has focus, then press → three times. The anchor reads 3 ms later. After about half a second "saved" appears, and the edits list gets one `tempo_map/1/anchor_ms` entry for the 3 ms.
5. Reload the page. The url holds `?job=...`, so the same job comes back, with the same bands and the same edits.
6. Pick `tempo-check.wav` again and press analyze. It says the file was analyzed before and offers "reopen" and "analyze again as a new job". Press "reopen".
7. Press "re-analyze". The second band stays as it was, 200.00 bpm · manual with the moved anchor, and the edits list is unchanged, because re-analysis isn't an edit. The first band is fitted again from the same audio.

Next the fast-song check:

```bash
python scripts/make_click_track.py fast-270.wav --bpm 270 --beats 160 --lead 0.4375 --accent
```

It should come out at 270.00 bpm, not 135. If a real fast song comes out at half its tempo, ×2 on its segment fixes it. The cases that are still ambiguous are off-beat eighth notes at 50 to 80% of the weaker beats' level, fast songs where every other beat is much quieter, and a switch to exactly half or double tempo on a steady beat (see "tempo range and half or double" in `docs/decisions.md`).

Don't commit the generated audio.

## Milestone 3b check

A 270 bpm track with eight bars of a dotted 3-3-2 rhythm in the middle. The chart tempo stays 270, so the map should too:

```bash
python scripts/make_click_track.py dotted-check.wav --bpm 270 --beats 288 --lead 0.6113 --accent --rhythm 128:32:0,1.5,3
python -m backend.analysis.cli dotted-check.wav -v
```

`--rhythm 128:32:0,1.5,3` means 32 beats from click 128 where the clicks play 0, 1.5 and 3 beats into each 4 beat bar. With madmom the CLI prints one segment at 270.0000 bpm and a `kept ... on this grid` line under it, at about 29388 to 35944 ms, 203.36 bpm on its own (3/4). In the UI the segment panel lists the section under "kept on this grid". "split out" gives three segments, 270.00, 203.36 and 270.00, and "match previous" on the middle one puts it back on the 270 grid as one edit.

For comparison, a real change of tempo at the same ratio that doesn't come back stays as two segments, 270.00 and 202.50:

```bash
python scripts/make_click_track.py modulation-check.wav --bpm 270 --beats 224 --lead 0.6113 --accent --change 128:202.5
```

Don't commit the generated audio.

## Milestone 3c check

A 260 bpm track where only the off-beats click for 32 beats:

```bash
python scripts/make_click_track.py offbeat-check.wav --bpm 260 --beats 288 --lead 0.5531 --accent --rhythm 128:32:0.5,1.5,2.5,3.5
python -m backend.analysis.cli offbeat-check.wav -v
```

With madmom the CLI prints one segment at 260.0000 bpm with its anchor on the first click (about 552.4 ms), and an `off-beat` line under it at about 30437 to 36899 ms. madmom follows the off-beat clicks there and takes a beat or two to go over and to come back. In the UI that stretch is hatched on the timeline and listed under "off-beat runs" in the segment panel.

Don't commit the generated audio.

## Milestone 4 check

The expected values below are for madmom.

First a meter change, a 140 bpm track that is 4/4 and then has 7 beats to the bar:

```bash
python scripts/make_click_track.py meter-check.wav --bpm 140 --beats 148 --lead 0.52 --accent --meter 64:7
python -m backend.analysis.cli meter-check.wav -v
```

`--meter 64:7` means click 64, counted from 0, is a downbeat and the bars from it on have 7 beats. The script prints the change at click 64, at 27948.571 ms.

The CLI prints one tempo segment at 140.0000 bpm with its anchor at 519.274 ms, then `meter   2 segment(s)` with `[0] 519.546 -> 27947.849 ms, 4/4` and `[1] 27947.849 -> 63550.363 ms, 7/4`, both with confidence 1.00. Seven beats of the grid come out as 7/4. Whether the chart writes that as 7/8 at twice the bpm is a notation choice the audio can't make, so set it in the meter panel if it does.

Then the UI check. Start the backend and the frontend as described in Running, upload `meter-check.wav`, and wait for the job to finish.

1. The meter panel under the zoomed view reads "meter 1 of 2" and 4/4. Click the waveform past 28 s and it reads "meter 2 of 2" and 7/4.
2. The bar lines on the timeline are every 4 clicks, and every 7 after the change.
3. With "meter 2 of 2" in the panel, set 3/4 with "set meter". The edits list shows `meter_map/1/numerator` (7 → 3), plus `meter_map/1/confidence` and `meter_map/1/source` (auto → manual). "split meter here" on a beat in the zoomed view logs the whole `meter_map` before and after instead.
4. Press "re-analyze". The manual meter stays.

Next half and double time, on a drum track at 130 bpm:

```bash
python scripts/make_drum_track.py drums-check.wav --bpm 130 --section 16:8:half --section 32:8:double
python -m backend.analysis.cli drums-check.wav -v
```

`--section 16:8:half` makes 8 bars from bar 16 a half time feel, and `--section 32:8:double` makes 8 bars from bar 32 a double time feel. The script prints the half section at bars 16 to 24 (30038.462 to 44807.692 ms, charted at 65.00 bpm) and the double one at bars 32 to 40 (59576.923 to 74346.154 ms, charted at 260.00 bpm).

The CLI prints one tempo segment at 129.9990 bpm and two `suggest` lines: `suggest half 30039.226 -> 44808.575 ms, 64.9995 bpm from 129.9990, score 0.63` and `suggest double 59577.924 -> 74347.272 ms, 259.9979 bpm from 129.9990, score 0.56`.

In the UI, upload `drums-check.wav` and wait for the job to finish.

1. The notation suggestions list has a "half time" row and a "double time" row.
2. Select the second one. The playhead moves to 59577.9 ms.
3. Press "apply" on the half time one. The tempo map becomes 130.00, 65.00 and 130.00 bpm, with the middle one manual and the bars in it twice as long. The edits list gets a `tempo_map` entry and a `notation_suggestions/0/status` entry.
4. Press "dismiss" on the other one. The edits list logs its status.
5. Press "re-analyze". Neither suggestion comes back.

The suggestions are tuned on these synthetic drums only, so run `scripts/eval_local.py` on your songs again and compare the `notation_suggestions` column with the charts. To let `tests/test_real_song.py` check MisoilePunch♪ (4/4 and no suggestions), YOUNITHM (half at the measures charted at 130, an expected failure for now) and ENDYMION (a fold for its outro), analyze each one again and copy its `beats.json` and `report.json` into `tests/real/<song>/` as before.

Don't commit the generated audio.

## Setting up a chart from the list

The chart setup panel lists what to type into a chart editor. These steps use MikuMikuWorld, the editor the list was checked against.

1. Convert the song to a wav with ffmpeg. The panel shows the command with the song's name filled in, which for an mp3 is:

   ```bash
   ffmpeg -i song.mp3 song.wav
   ```

   ffmpeg skips the decoder padding at the start of an mp3 the same way the analysis does, so the wav lines up with the timeline.
2. Load that wav as the song in the editor.
3. Type the offset labelled "with the wav from ffmpeg" into the music offset field. It is minus where measure 0 is in the audio, shown with 3 decimals, so a negative value is normal. A positive offset in MikuMikuWorld starts the song later.
4. Add each bpm and time signature change at the measure the list gives, in order. Measures count from 0, like the bar numbers on the timeline. A row marked mid-measure is not on a bar line, so put it at the listed beat inside the measure, where beat 1 is the bar line.

To use the original mp3 in the editor instead, type the second offset, "with the original mp3". MikuMikuWorld plays the mp3's decoder padding, so that offset is the padding further negative. For MisoilePunch♪, measure 0 is at `62.362` ms, so the offset is `-62.362` ms with the wav. The mp3 has `23.021` ms of decoder padding, so the offset is `-85.382` ms with the mp3. Both offsets are always shown. The decoder compensation setting of the Sonolus export does not apply here.

"copy list" copies the two offsets and one line per change. "more decimals" shows the bpm with 4 decimals instead of 2. Clicking a row moves the timeline and the zoomed view to that change and gives its label on the timeline the accent.

The tool never cuts the audio. Trim only marks where the music starts, so the offset is what tells an editor that plays the file from 0 ms where the first measure is.

## Sonolus export

"sonolus" in the export block, or `GET /api/jobs/<job id>/export?preset=sonolus`, gives:

- `level_data`: `bgmOffset` and one `#BPM_CHANGE` entity per tempo (with `#BEAT` and `#BPM`), in Sonolus' own level data shape. A level's own entities (initialization, stage, notes) go next to these.
- `bpm_changes`: the same changes, each with its time in ms on the report's timeline, for checking against the tempo map.
- `time_signatures`: the meter as beat positions. Sonolus level data has no time signature, so these are for the chart editor. A bar that a tempo change or a meter split cuts short gets its own entry.
- `first_downbeat_beat`: the beat the song's first downbeat lands on.

Level time 0 is beat 0, and the bgm plays at level time + `bgmOffset` seconds, which is how the official Sonolus converters use it. Beat 0 is a bar line at or before the start of the audio, so the intro isn't cut and `bgmOffset` is 0 or negative before decoder compensation. Where these conventions come from is in `docs/decisions.md` (Sonolus export).

Decoder compensation is how many ms later than ffmpeg the player's decoder plays the audio. It's 0 by default, which is right for a decoder that honours the gapless info in an mp3 or m4a. The other preset is the file's decoder padding, like 25.057 ms for an mp3 from lame, for a decoder that plays the padding. Only `bgmOffset` changes, every beat stays where it is. A wav or flac has no padding, so only 0 is offered.

The default is still 0 ms, and which preset is right for the real Sonolus app is still open. It waits on the test level in "Checking the offset in Sonolus" below, and there is no result from it yet.

The same from the command line:

```bash
python -m backend.analysis.export data/jobs/<job id>/report.json --sonolus --decoder-padding
python -m backend.analysis.export data/jobs/<job id>/report.json --beats data/jobs/<job id>/beats.json
```

## Milestone 5 listening check

The expected values below are for madmom.

Generate the accented 120 bpm click track from milestone 2 and an mp3 of it:

```bash
python scripts/make_click_track.py click-137.wav --bpm 120 --lead 0.1375 --accent
ffmpeg -i click-137.wav -b:a 192k click-137.mp3
```

Start the backend and the frontend as described in Running, upload `click-137.mp3`, and wait for the job to finish. The first downbeat reads about 136.78 ms and the decoder padding 1105 samples.

1. Press "click track", then play. Each generated click should have a click track click on it, and every 4th, the louder and higher generated one, an accented click. Listen for a flam (two attacks a few ms apart). There shouldn't be one. The clicks are a different pitch from the track's, so both stay audible.
2. With the click track on, press → five times quickly with the timeline focused. The clicks move 5 ms later and the flam is clear. Press ← five times to come back. That's two edits, and the edits list shows each as one row.
3. Click "split here" on a beat in the zoomed view, then ×2 on the second segment. The clicks double from that beat on, and the accents follow the bar lines. The edits list has one row per change. The ×2 row has a line for the bpm and one for the confidence, the split already made both halves manual.
4. In the export block, pick "timing json" and press "export json". A file named `click-137.timing.json` downloads, and the report in it has the same tempo map and edits as the report column. Tick "include beats.json" and export again. The file now has a `beats` section.
5. Pick "sonolus" and the 25.057 ms preset and export. `bgmOffset` is −1.838163 and `first_downbeat_beat` 4, the same as before the split, and `bpm_changes` has 120 bpm at beat 0 and 240 bpm at the beat of the split.
6. Re-analyze. The manual segments stay, the click track follows them, and the edits list is unchanged.

Then a real song. Play it with the click track on from a few bars in. If the accents drift off the downbeats, the tempo map is off there, and the timeline shows where.

Don't commit the generated audio.

### Checking the offset in Sonolus

This checks the Sonolus preset in the real app, including how its player decodes the audio, which can't be checked from here.

1. Export `click-137.mp3` with the sonolus preset twice, once at 0 ms and once with the 25.057 ms preset, as `click-0.sonolus.json` and `click-25.sonolus.json`.
2. Make level data with a tap note on every beat for each of them:

   ```bash
   python scripts/make_sonolus_test_level.py click-0.sonolus.json click-0.data.gz --beats 32
   python scripts/make_sonolus_test_level.py click-25.sonolus.json click-25.data.gz --beats 32
   ```

   The notes default to the pjsekai engine's `NormalTapNote` with `lane` 0 and `size` 1.5. For another engine, give its tap note with `--archetype` and its data with `--data name=value`.
3. Make two levels with `click-137.mp3` as the bgm and each data file as the level data, served the way you serve your levels (the engine's dev server or your own server).
4. Play each in auto play with note sound effects on. In the one that's right, every note's sound lands on a click of the bgm. In the other, they're about 25 ms apart, a clear flam. If the 0 ms level is right, Sonolus' decoder honours the gapless info on this device. If the 25 ms one is, it doesn't, and that preset is the one to use for mp3s on it. Do the same with an m4a if you use them, its padding is different.
5. To be sure which way is which, add 0.05 to `bgmOffset` in the right level by hand. The notes should then come 50 ms after the clicks, since the bgm is further in at every level time.

Do this once per device and player you chart for, and keep the compensation that worked. The export block remembers the last value.

## Docs

- `docs/setup-guide.md`: the install and running steps one at a time, from a machine with nothing installed.
- `docs/architecture.md`: how the pieces fit together.
- `docs/decisions.md`: thresholds, measured accuracy, and what broke.
- `docs/schema-changelog.md`: one line per schema change.
