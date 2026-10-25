# starstep-meter

Beat, tempo, and meter analysis for rhythm game charting. Upload a song, get a beat grid and a ms-accurate first-downbeat offset, check it on a waveform timeline. Runs locally.

*✦ star steps, right on the beat ✦*

## What it does and doesn't do

starstep-meter runs on your own machine. You upload a song in the browser, and the backend decodes it with ffmpeg, finds where the music starts and ends (the trim), and tracks beats and downbeats with madmom, or with a librosa fallback when madmom isn't installed. It checks the tracked tempo for half or double time, snaps each beat onto the nearest onset, and splits the beats into tempo segments. Each segment gets its own bpm and its own anchor, the time of its first downbeat, from a linear fit through its beats. It then infers the meter of each segment, suggests where a chart might write the pulse at half or twice the tempo, runs librosa's beat tracker as a second opinion, and gives every segment and every stretch of 16 grid beats a confidence.

The browser shows a waveform timeline with the segments as bands and the beat grid on them, a zoomed view for checking the grid against an attack, a click track to check it by ear, and a list of what to type into a chart editor (the music offset and every bpm and time signature change by measure). Every manual change is recorded in an edit log. The result downloads as a timing JSON. A CLI does the same analysis for one file without the server.

What it doesn't do:

- It doesn't find sections of a song.
- It doesn't cut or change the audio. The trim only marks where the music starts and ends, and every time in the report is in milliseconds from the first decoded sample.
- It doesn't write charts or place notes.
- It has no accounts and no sharing. The server binds to 127.0.0.1, exports contain timing data only and never audio, and uploaded audio is kept only in the local `data/` folder.

For a step-by-step install from a machine with nothing on it, see `docs/setup-guide.md`.

## Status

What works:

- On generated click tracks the bpm comes out within 0.0002 of the true value and the first downbeat within about 1 ms, through wav, mp3, m4a and ogg, at 44.1 and 48 kHz. The test tolerances are 0.01 bpm and 5 ms.
- Tempo changes on click tracks are found with the right bpm and change point. Dotted and triplet feel sections and stretches where the tracker followed the off-beat are kept on the notated grid instead of being split off.
- The three real songs checked so far come out at their charted tempos (MisoilePunch♪ at 270, YOUNITHM at 260, ENDYMION at 220) as one long segment each. ENDYMION's outro is split off as two short ones.
- The cross-check against librosa flags only one stretch on those three songs, the 267.87 bpm part of ENDYMION's outro, which the chart has at 220.

Known to be imperfect:

- The thresholds are tuned on generated click and drum tracks and on three real songs. On other music, check the bands, the bar lines and the suggestions, and fix them by hand where they are wrong.
- The half and double time suggestions found nothing on the three real songs. Their drums show no plain backbeat in the three frequency bands the detector reads, so there is nothing for it to find, and the stretches YOUNITHM charts at half tempo are the stretches without drums. A missed suggestion was judged cheaper than a wrong one, so the detector was left as it was. Half and double time are set with the bpm buttons.
- The onset snap barely refines madmom's beats on full mixes. On the real songs it moves 80% of the beats by no more than about 2.6 ms after the bias shift. So on real music the timing rests on madmom's own beats plus the 11.8 ms bias that was measured on click tracks.
- That bias is not the same on every song. On MisoilePunch♪ the grid sits about 7 ms earlier than librosa's beats and than what sounded right by ear. Nothing is changed for it, because a correction tuned on one song would move every other song. Nudging the anchor by hand with the click track on is the way to correct it.
- Sections are not detected.
- The librosa fallback holds one tempo, so it can't follow tempo changes or felt sections, its downbeat is a guess, and its confidence is halved.
- The denominator of an inferred meter is always 4. Seven beats of the grid are 7/4, and whether a chart writes that as 7/8 at twice the bpm is a notation choice the audio can't make.
- ENDYMION's outro is left as two short segments. A fold suggestion offers to put it on the neighbouring grid.

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

This has not been tested on Windows yet. It worked on Linux with Python 3.11 and 3.13.

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

### Backend

The backend is `python -m backend.api`. It serves on http://127.0.0.1:8000 and is only reachable from this machine. Use `--port` to change the port. There is also a `--host` option, but any value other than localhost prints a warning, and it is not meant for normal use.

```bash
python -m backend.api
```

### Frontend

In a second terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open http://127.0.0.1:5173 in the browser. Vite proxies `/api` to the backend, so both need to be running. The header shows what was found, like `ffmpeg ok · ffprobe ok · madmom ok`. Without madmom it reads `madmom not installed`, and with a madmom that is installed but doesn't import it reads `madmom failed to import`, with the error in its tooltip. If the backend isn't running it reads `backend offline`.

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

With `-v`, stage progress and debug numbers go to stderr, so stdout stays pipeable. The lines are:

- `beats`: the tracker and how many beats it found.
- `octave`: one line per rough tempo segment, with what the half or double check did, the tracked bpm, and the midpoint and parity ratios it decides on.
- `snap`: how many beats snapped to an onset, the bias shift applied to madmom's beats before the search, and the median move.
- `tempo`: the number of segments, the residual rms, the outliers and the confidence, followed by one `[i]` line per segment with its start and end, bpm, anchor and beat count.
- `meter`: how many meter segments and how many grid positions were read, with one `[i]` line per meter segment (start, end, numerator/denominator and confidence).
- `suggest`: one line per notation suggestion, with its kind, start and end, the suggested bpm and the bpm it was made on, and the score.
- `check`: the librosa cross-check, with how many beats librosa found and the distance above which a segment is flagged. One `[i]` line per tempo segment gives the median distance between the two trackers' beats, how many beats were compared, and `flagged` when it is over the limit (or `too few beats to compare`). When librosa is the main tracker, the line says there is no cross-check.
- `conf`: the confidence of each tempo segment and how many of the 16 beat spans are low, followed by one `low` line per low span with its start and end and its confidence.

The options:

- `--threshold-db` sets the trim threshold.
- `--tracker auto|madmom|librosa` picks the beat tracker. `auto`, the default, uses madmom when it's installed and falls back to librosa otherwise. `madmom` is an error if madmom is missing or fails to import, and `librosa` skips madmom.
- `--snap-window-ms` sets how far onset snap may move a tracked beat, 20 ms by default.
- `--cross-check-ms` sets how far apart madmom's and librosa's beats may be in a tempo segment before it is flagged, 20 ms by default.
- `--min-bpm` and `--max-bpm` set the slowest and fastest tempo any tempo path considers, 60 and 320 by default.
- `--beats PATH` also writes the beats file to PATH, and the report still goes to stdout.
- `--work-dir` keeps the copied original and the decoded WAV in a folder you choose instead of a temp dir.

## Using it

The workflow below goes from a song to a chart set up in an editor. The page is lowercase throughout, and the names in backticks are what the buttons and labels say.

### 1. Upload and analyze

Press `choose audio file`, pick an mp3, wav, flac, ogg or m4a file, and press `analyze`. The progress pills in the source column run through `upload`, `decode`, `trim`, `beats`, `snap`, `tempo`, `meter`, `check` and `done`. A 4 minute song takes under a minute with madmom. If a stage fails, the message names it, like `analysis failed at decode — check that ffmpeg is on PATH`.

When the job is done, the page shows the `for your chart` card above the timeline, the timeline itself, and the controls and panels under it.

### 2. Read the plain answer

The `for your chart` card at the top is the short version of the whole analysis, in words that don't need the technical panels. It is worked out from the chart setup list further down, so its numbers can't differ from that list.

- `bpm` is the tempo of the song. When the speed changes, it reads `bpm at the start` and gives the first one.
- `offset` is the number to type into a chart editor's music offset field. It is minus the place where measure 0 starts in the song. Measure 0 is one empty bar before the bar the music starts in, so the offset is negative after a long silence at the start and positive when the silence is shorter than a bar. There are two: `if you load the wav made with ffmpeg`, and, only when the original file has decoder padding, `if you load the original mp3` (or m4a, or whichever the original is). Step 6 explains the difference.
- `time signature` is the one at the start, like `4/4`.
- Each of the three has a `?` button that opens a one line explanation.
- When the bpm or the time signature changes, a line says so, like `this song changes speed 3 times and changes time signature once`, with a `see every change` link to the chart setup list.
- When a stretch under an automatic segment came out with low confidence, a warning says `parts of this song were hard to read, check the shaded areas`. Those are the shaded stretches on the timeline, see step 4.
- `more decimals` shows the bpm with 4 decimals instead of 2, and `copy` copies the card as text.

For a steady song with no warning, the card is all that is needed. If the card shows changes or a warning, or if the song doesn't sound right against the grid, go on to the next steps.

### 3. Check the grid with the click track and the zoomed view

The timeline shows the waveform with the beat grid on it and the tempo segments as bands. Each band has a label along the bottom, like `200.00 bpm · manual` (`· manual` only appears once the segment was edited by hand). The numbers along the top are bar numbers. The music starts at the trim start, or at the first tracked beat when that is earlier. The bar it starts in, the last bar line at or before that point, is measure 1, and measure 0 is one empty bar of lead-in before it. When the song starts with a pickup, the bar the pickup is in is measure 1. Bars before measure 0 are the silence the offset skips, so they are drawn faintly and have no number. Bar lines before 0 ms of the audio file are not drawn. These are the same numbers the chart setup list and the `for your chart` card use. The setting `music starts at measure` in the chart setup panel (step 5) can put the music at measure 0 instead.

Clicking the waveform selects the tempo segment under the click (in a song with more than one segment, its band gets the pink accent) and puts the nearest tracked beat in the zoomed view. The `−` and `+` buttons next to the time zoom the timeline between `fit` and `2000 px/s`. Space plays and pauses while the waveform has focus.

The zoomed view under the transport draws the decoded wav at its own sample rate. Its caption reads like `tracked 944.068 ms · grid +7.170 ms`, the time of the tracked beat and how far the nearest grid line is from it. The `40 ms`, `120 ms` and `400 ms` buttons set how wide it is. At 40 ms the grid line should sit on the attack of the beat.

`click track` next to `play` turns the click track on and off. It clicks on every beat line of the grid and plays a higher, louder click on every bar line, so it follows the tempo map, the meter and an anchor while it's being nudged. The clicks are scheduled on the same audio clock as the song, so they stay with it however long it plays. Listen for a flam, two attacks a few ms apart. Where the click track and the song don't line up, the grid is off there.

Under the play time, a line says how far behind the audio the playhead is drawn, like `playhead −42.0 ms output latency`. It is the output latency and base latency the browser reports, and it is read again as the device changes. Only the drawing moves, the music and the clicks are not. When the browser reports no output latency, the line says the playhead isn't compensated. On Bluetooth the reported number may still be off, and the sound comes out later than the playhead moves, the clicks and the song together, so watch the playhead on wired output.

### 4. Fix segments and meter if needed

Everything in this step acts on the selected segment or on the beat in the zoomed view. Every change shows up in the report's `edits` list, one entry per change. Splitting or merging a segment that the analysis fitted refits it from the tracked beats, while a segment whose bpm or anchor was set by hand keeps its grid.

The segment panel (in the right column on a wide window) has the heading `segment 1 of 2` and says whether the segment is `auto` or `manual`. Its second line gives the confidence and the cross-check, like `confidence 0.89 · librosa 7.13 ms apart`. A segment set by hand says `set by hand` instead of a confidence. When the two trackers are further apart than the limit it adds `over 20 ms`, and it says `no cross-check` or `too few beats to cross-check` where there was none.

- The bpm has `÷2`, `×2`, `×3/4`, `×4/3`, `×2/3` and `×3/2` buttons, and a field with a `set bpm` button for an exact value. They keep the anchor and rebuild the grid from it. The 60–320 bpm range is only for detection, a value set here can go up to 1000.
- The anchor moves in 1 ms steps with the `−1 ms` and `+1 ms` buttons, and with ← and → while the timeline has focus. A change is saved about half a second after the last step.
- `anchor here` rebuilds the grid from the tracked beat in the zoomed view, and `split here` splits the segment at that beat.
- `merge ←` and `merge →` merge the segment with the one before it or after it.
- `match previous` and `match next` join the segment to its neighbour with the neighbour's bpm and anchor, as one edit. That's for a stretch that is the same tempo felt differently.
- When the analysis kept a felt section (a dotted or triplet rhythm) on the segment's grid, the panel lists it under `kept on this grid` with its own bpm and ratio, like `203.36 bpm (3/4)`. `split out` splits at both its ends, as one edit, so it gets its own tempo back. The report's tempo map list shows the same sections.
- Where the beat tracker followed the off-beat for a while, the timeline hatches that stretch and the panel lists it under `off-beat runs` with its start, end and beat count. The grid stays on the beats there.

Stretches the analysis is less sure of are shaded on the timeline: a darker wash with a dotted edge along the bottom and a `low confidence` label. Each is a span of 16 grid beats whose confidence is under 0.5. The confidence comes from how many beats sit within 10 ms of the grid and how well librosa's beats agree, and the formula is in the confidence section of `docs/decisions.md`. Only spans under automatic segments are shaded, because the spans were measured on the analysis' grid and a segment set by hand has a different one.

Each tempo or time signature change after the first gets a label on the timeline at its bar line, like `m.24 · 150.00 bpm` or `m.37 · 3/4`. One label shows both when they share a line, and when zoomed out a label that would run into the one before it is left out. The chart setup list has every one of them.

The meter panel sits under the zoomed view. It acts on the meter segment at the beat in the zoomed view, and its heading says which one, like `meter 1 of 2`. The numerator and denominator fields with the `set meter` button set that segment's meter by hand. `split meter here` starts a new meter at the beat in the zoomed view, and the bars restart there. `merge ←` and `merge →` merge the segment with the one before it or after it. A bar is numerator × 4 / denominator beats of the grid, so 7/8 is three and a half beats. The bar lines on the timeline come from the meter map.

Under the segment panel is the `notation suggestions` list. Each open suggestion shows its kind (`half time`, `double time` or `fold into neighbour`), its start and end, the suggested bpm with the bpm it was made on, and a score from 0 to 1. Selecting one moves the playhead and the zoomed view to its start and highlights its mark on the timeline. `apply` and `dismiss` decide it, and the decided ones are counted in one line, like `1 applied, 2 dismissed`. The thin marks along the top of the timeline, under the bar numbers, are the open suggestions. Suggestions are never applied automatically, and both decisions stay through re-analysis.

Applying a half or double time suggestion splits the segment at both ends of the span, on bar lines, and sets the span to half or twice its bpm, so the bars there are twice or half as long, and every grid line stays where it is. A fold puts the stretch on its neighbour's grid, the way `match previous` and `match next` do. Applying is one edit, and dismissing only logs the status.

### 5. Read the chart setup list

The `chart setup` panel under the notation suggestions lists what to type into a chart editor. It has three parts.

- `music offset` has the setting `music starts at measure` with the buttons `0` and `1`. The default is 1, and the choice is remembered in the browser. Under it are two values, `with the wav from ffmpeg` and `with the original mp3` (the original's extension), and a note saying where the music starts and which measure it is in, like `the music starts in measure 1, at 62.362 ms, and measure 0 is one empty bar of lead-in before it`, and where measure 0 starts, either `into the audio file` or `before the audio file starts`.
- `audio file` shows the ffmpeg command that makes the wav, with a `copy command` button.
- `bpm and time signature changes, in order` lists the first bpm and time signature and every change after them, like `m.24 · 150.00 bpm` or `m.37 · 3/4`. Measures are numbered the way the timeline numbers its bars, so measure 0 is the empty bar before the music, or the bar the music starts in when `music starts at measure` is 0. A row marked `mid-measure` is not on a bar line, and its row says where inside the measure it goes, like `beat 3`, where `beat 1` is the bar line.

`copy list` copies the two offsets and one line per change. `more decimals` shows the bpm with 4 decimals instead of 2. Clicking a row moves the timeline and the zoomed view to that change and gives its label on the timeline the accent.

### 6. Set up the chart in an editor

These steps use MikuMikuWorld, the editor the list was checked against.

1. Convert the song to a wav with ffmpeg:

   ```bash
   ffmpeg -i song.mp3 song.wav
   ```

   The panel shows the command with the song's name filled in and in quotes, like `ffmpeg -i "song.mp3" "song.wav"`, and `copy command` copies it. For a wav source the output is named `song-ffmpeg.wav`, so ffmpeg doesn't write over the original. ffmpeg skips the decoder padding at the start of an mp3 the same way the analysis does, so the wav lines up with the timeline.
2. Load that wav as the song in the editor.
3. Type the offset labelled `with the wav from ffmpeg` into the music offset field. Offsets are minus where measure 0 starts in the audio, shown with 3 decimals. After a long silence measure 0 is inside the file and the offset is negative. When the silence before the music is shorter than a bar, measure 0 starts before the file and the offset is positive, which is normal. A positive offset in MikuMikuWorld starts the song later.
4. Add each bpm and time signature change at the measure the list gives, in order. A row marked `mid-measure` is placed at the listed beat inside the measure.

To use the original mp3 in the editor instead, type the second offset, `with the original mp3`. MikuMikuWorld plays the mp3's decoder padding, so that offset is the padding further negative, and the two offsets differ by exactly the padding. The panel works that out before rounding. For MisoilePunch♪, the music starts on the bar line at 62.362 ms, which is measure 1, and measure 0 starts one bar earlier, at -826.515 ms, before the file. So the offset is `826.515` ms with the wav. The mp3 has 23.021 ms of decoder padding, so the offset is `803.494` ms with the mp3. The padding is shown in the report column (`decoder padding`) and in the note under the offsets.

The offset is positive here because the silence before the music is shorter than a bar. With a longer silence it is negative. A click track with 8 s of silence at 145.99 bpm has its first downbeat at 7999.268 ms, which is measure 1. A bar is 1643.948 ms, so measure 0 starts at 6355.320 ms and the offset is `-6355.320` ms with the wav. The silence before measure 0 is skipped by the offset. If the editor, or your habit, wants the music at measure 0, press `0` next to `music starts at measure`. The bar the music starts in is then measure 0, with no lead-in bar, and the offset is minus where that bar starts: `-62.362` ms for MisoilePunch♪ with the wav, and `-7999.268` ms for the 8 s example. Both offsets are always shown.

The tool never cuts the audio. The trim only marks where the music starts, so the offset is what tells an editor that plays the file from 0 ms where measure 0 is.

### Reopening, re-analyzing and deleting jobs

The url carries the job id (`?job=...`), so a reload reopens the job with its edits. The `recent` list in the source column shows recent jobs, newest first, and any of them can be reopened. Picking a file that was analyzed before and pressing `analyze` says `this file was analyzed before` and offers `reopen` for each earlier job and `analyze again as a new job` to start over.

`re-analyze` runs the analysis again on the stored upload and keeps the manual segments, the decided suggestions and the edit log. If a re-analysis fails, the last good report stays on screen with a note saying at which stage the re-analysis failed.

Each job in the `recent` list has a `delete` button. It asks `delete this job and its files?` first, and deletes only on the second press, upload and decoded wav included. The button is not shown for a job that is queued or running, and the server refuses to delete one. The same can be done from the command line with the job id from the url:

```bash
curl -X DELETE http://127.0.0.1:8000/api/jobs/<job id>
```

### Storage

Each job keeps a copy of the upload, the decoded WAV, and `beats.json` (every tracked beat, with its raw and snapped time) under `data/jobs/<job id>/`. `beats.json` also holds the band strengths (low, mid and high) at every grid line and half line. They are timing numbers only, and they let the suggestions be checked again without the audio. It also holds librosa's snapped beats (`cross_check_beats`), also timing only, so the cross-check and the confidence can be worked out again without the audio. The decoded WAV is mono float32, about 10 MB per minute at 44.1 kHz.

When the server starts, it deletes job folders that haven't changed for 14 days (`STARSTEP_RETENTION_DAYS`). A change is the upload, an analysis or re-analysis, or an edit, so a job you're still editing stays, and one you only open or export doesn't count as changed. `data/` is git-ignored.

A job that was still waiting in the queue when the server stopped runs when it starts again. One that was in the middle of its analysis is marked failed instead ("server restarted before the job finished"), and `re-analyze` runs it again.

## Export

The export block in the source column downloads the timing JSON, the report as it is. `include beats.json` adds the beats file, and the choice is remembered in the browser. The file is named after the song, like `song.timing.json`. It is checked against the JSON Schema in `shared/schema/` before it goes out, and it never contains audio.

The same from the command line, with the report and beats files from a job folder:

```bash
python -m backend.analysis.export data/jobs/<job id>/report.json --beats data/jobs/<job id>/beats.json
```

It prints the timing export with the beats file in it to stdout. Leave out `--beats` for the report alone.

There used to be a Sonolus preset here as well. It was removed in milestone 7, before its offset had been checked in the real app. The decoder padding it compensated for is still in the report, and both offsets in the chart setup list and the `for your chart` card account for it.

## Real songs: eval_local.py

The thresholds for the trim, the onset snap, the half or double check and the tempo map are tuned on synthetic tracks and three real songs. `scripts/eval_local.py` runs the same analysis on a folder of your own songs and writes a csv of timing numbers, one row per song, to paste into a later session for tuning them on more real music. It needs ffmpeg and ffprobe on PATH, and it looks for mp3, wav, flac, ogg and m4a files.

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
- `segments` is the number of tempo segments, and `segment_starts_ms`, `segment_bpms` and `segment_confidences` list each segment's start, bpm and confidence in order, separated by spaces. The confidence is worked out from the fit residuals and the cross-check agreement (see the confidence section of `docs/decisions.md`), and halved for the librosa fallback.
- `residual_rms_ms` is the rms distance in ms of the beats that fit their grids, and `residual_p95_ms` and `residual_max_ms` are the 95th percentile and the largest distance over all beats, each measured from the grid of the beat's own segment. A beat in a felt section or an off-beat run is measured from the subdivision it sits on.
- `outliers` is the number of beats that were too far from their grid to count as fitting it.
- `confidence` is the share of all beats within 10 ms of their grid, halved for the librosa fallback.
- `ratio_merged` lists the felt sections kept on their segment's grid, like `3/4:44511-58724` (the ratio, then start and end in ms), and `offbeat_runs` the stretches where the tracker followed the off-beat, like `48664-52872`. Both are separated by spaces and empty when there are none.
- `meter` lists the meter segments, like `4/4:97 7/4:27948` (the signature, then start in ms), and `notation_suggestions` the suggestions, like `half:97-37020:0.62` (the kind, start and end in ms, then the score). Both are separated by spaces and empty when there are none.
- `cross_check_ms` has one value per tempo segment, separated by spaces: the median distance in ms between madmom's and librosa's beats. A `-` means there were too few beats to compare, and a `!` after the number means the segment was flagged. It is empty when there was no cross-check.
- `low_confidence` lists the spans of 16 grid beats with a confidence under 0.5 as `start-end:confidence`, with start and end in ms, separated by spaces and empty when there are none.
- `beats`, `beats_snapped` and `beats_not_snapped` are how many beats the tracker found and how many did and did not find an onset inside the snap window.
- `median_snap_move_ms` is the median distance in ms that a beat moved from the tracker's output to where it snapped, including the 11.8 ms bias shift for madmom. It was meant as a real-song check of madmom's bias, but on full mixes it can't confirm it. The snap barely moves most beats there, so the value comes out near the shift whether or not the bias holds (the real songs gave 11.6 to 11.9 ms). A value far from 11 ms still means the beats are moving a lot onto onsets, and is worth a look.
- `error` is empty for a song that worked, and otherwise holds a one-line message.

A song that fails gets a row with only `file` and `error` filled in, and the run carries on with the next song.

## Real songs: measure_bias_local.py

madmom's beats are shifted 11.8 ms later before the onset snap. That bias was measured on click tracks, and on full mixes the snap barely moves the beats, so the analysis can't tell whether it holds on real music (see "grid timing at the start of MisoilePunch♪" in `docs/decisions.md`). `scripts/measure_bias_local.py` measures it on a folder of your own songs:

```powershell
python scripts\measure_bias_local.py C:\path\to\songs --recursive --out results\bias.csv
```

It needs ffmpeg, ffprobe and madmom. For each song it takes madmom's raw beats, without the bias shift, the snap or the octave check, and finds the strongest onset within `--window-ms` (30 ms by default) of each beat, with the same short-window spectral flux the snap uses. A beat whose strongest flux peak is under 20% of the median over all beats is skipped, the way the snap skips it. `--threshold-db` sets the trim threshold, and `--out` is the csv, `measure_bias.csv` in the current directory by default.

An offset is the raw beat minus the onset in ms, so a negative value means madmom is early, the same sign as the bias. The csv has one row per song, timing numbers only, never audio:

- `file`, `duration_ms` and `sample_rate` say which song it is.
- `beats` is how many beats madmom found, and `beats_with_onset` how many had a usable onset.
- `median_offset_ms`, `mean_offset_ms` and the 10th, 25th, 75th and 90th percentiles (`p10_offset_ms` and so on) describe the offsets of that song, and `iqr_ms` and `mad_ms` (the median absolute deviation, unscaled) their spread.
- `bias_ms` is the bias the analysis uses, and `median_minus_bias_ms` the median offset minus it. That is about where a beat shifted by the bias sits against the onsets, positive meaning late.
- `error` is empty for a song that worked. A song that fails gets a row with only `file` and `error`, and the run carries on.

If the bias holds, the medians sit near −11.8 ms. On click tracks they read about −11.1, because the flux peak lands about 0.7 ms before a click's first sample. One song can be several ms off depending on where madmom's 10 ms frames fall, so judge by the folder median, which the last line on stderr prints along with how many songs failed.

## Tests

Backend tests run from the repo root:

```bash
python -m pytest
python -m backend.schema.export_schema --check
```

Tests that need ffmpeg are skipped, not failed, when it is missing, and the madmom tests are skipped when madmom isn't installed. The tempo map tests run on synthetic beat lists and click tracks with known change points and felt rhythm sections. The meter and notation tests run on click tracks with meter changes and on generated drum tracks with half and double time sections. `tests/test_cross_check.py` and `tests/test_confidence.py` run on beat lists, and the confidence tests also on click tracks with a messy section, felt sections and an off-beat section. Test audio is generated in code and cached in `tests/fixtures/`, which is git-ignored.

`tests/test_real_song.py` checks the tempo map on real songs' `beats.json` and `report.json`, one folder per song under `tests/real/` (for example `tests/real/endymion/`). That folder is git-ignored, it holds timing data only, and a song's tests skip when its folder is missing. The test also runs the notation suggestions again from `beats.json`, and skips that part for a song whose beats file has no band strengths (`grid_features`). It checks the confidence on the real songs too: no low confidence on MisoilePunch♪'s felt sections or on YOUNITHM's off-beat runs, and low confidence only where the trackers struggled. The cross-check is included when `beats.json` has `cross_check_beats`: it must flag only ENDYMION's outro, and that test skips for a song whose beats file has none. Without `cross_check_beats` the confidence is worked out from the residuals alone. To refresh a song, analyze it again and copy `beats.json` and `report.json` from `data/jobs/<job id>/` into `tests/real/<song>/`.

Frontend checks run from `frontend`:

```bash
cd frontend
npm test
npm run check:types
npm run build
```

`npm run typecheck` runs the TypeScript check on its own. The frontend tests cover the beat-to-pixel mapping, the tempo map grid with the bar lines from the meter map, the edit queue, the suggestion helpers, the job url helpers, job deletion, the edit log rows, the export options, the chart setup list, the plain answer card, the wav reader, the playhead latency, and the click track and player on a fake audio context.

When you change `backend/schema/models.py` or `backend/schema/export_models.py`:

1. Run `python -m backend.schema.export_schema`. It writes every schema in `shared/schema/`: the report, the beats file and the two exports.
2. In `frontend`, run `npm run gen:types`. It regenerates one TypeScript file per schema in `frontend/src/types/`.
3. Add a line to `docs/schema-changelog.md`. Bump `schema_version` for breaking changes.

## Dependencies and licenses

This project's code is licensed under PolyForm Noncommercial 1.0.0 (see `LICENSE`), so it is for noncommercial use only.

madmom is used for beat and downbeat tracking when it's installed. Without it, the librosa fallback runs with lower confidence and a guessed downbeat. madmom's code is BSD-licensed, and its pretrained models carry their own CC BY-NC-SA 4.0 terms. This project does not redistribute madmom or its models. Whoever runs the tool installs them separately.

The versions below are the ones the tests ran on, with Python 3.13. The licenses and versions were read from the installed packages' own metadata (Python `importlib.metadata`) and from `package-lock.json` on 2026-10-25.

### Python runtime

| Package | Version | License | Notes |
|---|---|---|---|
| fastapi | 0.162.0 | MIT | |
| pydantic | 2.14.1 | MIT | |
| uvicorn | 0.54.0 | BSD-3-Clause | |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |
| soundfile | 0.14.0 | BSD-3-Clause | Wheels bundle libsndfile, which is LGPL-2.1 |
| librosa | 1.0.0 | ISC | |
| python-multipart | 0.0.32 | Apache-2.0 | |
| jsonschema | 4.26.0 | MIT | Checks every export against the committed JSON Schema before it goes out |

### Pulled in by librosa

These come in through librosa. soxr is LGPL-2.1-or-later, so it is the one to watch.

| Package | Version | License |
|---|---|---|
| scipy | 1.18.1 | BSD-3-Clause |
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

`pyproject.toml` and `package.json` allow newer versions than the ones listed.

## License

PolyForm Noncommercial 1.0.0, see `LICENSE`. The code may be used for noncommercial purposes only.

## Docs

- `docs/setup-guide.md`: the install and running steps one at a time, from a machine with nothing installed.
- `docs/roadmap.md`: the project history by version, and the manual checks to run for each one.
- `docs/architecture.md`: how the pieces fit together.
- `docs/decisions.md`: thresholds, measured accuracy, and what broke.
- `docs/schema-changelog.md`: one line per schema change.
