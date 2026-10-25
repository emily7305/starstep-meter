# Setup guide

This is the long version of the install and running sections of the README, one step at a time, from a Windows machine with nothing installed to a song set up in a chart editor. Windows comes first because it's the main machine for this project. Linux is at the end. If the two ever disagree, the README is the reference and this guide gets updated to match.

Run every command in order, and wait for each one to finish before starting the next.

## What runs where

Two programs run at the same time, both only reachable from this machine:

- The backend, in Python, does the analysis. It serves http://127.0.0.1:8000.
- The frontend, in Node, is the page you use. It serves http://127.0.0.1:5173 and passes `/api` requests on to the backend.

A terminal is the window the commands go into. On Windows this guide uses PowerShell (Windows key, type `PowerShell`, Enter). The repo folder is the `starstep-meter` folder with the project in it. The virtual environment is the `.venv` folder inside it, which holds this project's Python packages apart from everything else on the machine.

## Part 1: install the tools (once)

### Step 1: Git

```powershell
winget install Git.Git
```

Close PowerShell and open a new one, so the new PATH is picked up. The same goes for every install below.

### Step 2: Python 3.11

```powershell
winget install Python.Python.3.11
```

In a new PowerShell, check it:

```powershell
py -3.11 --version
```

It should print `Python 3.11.x`.

### Step 3: ffmpeg

ffmpeg decodes the audio and ffprobe reads what's in the file. Both come in one package:

```powershell
winget install Gyan.FFmpeg
```

In a new PowerShell, check both:

```powershell
ffmpeg -version
ffprobe -version
```

Each prints a few lines of version info. The README describes installing it by hand instead, if winget isn't an option. ffmpeg is also used at the end of this guide, to turn a song into the wav that goes into the chart editor.

### Step 4: Node 22.12 or newer

vitest 5 needs 22.12 at least, so the LTS release is the one to install:

```powershell
winget install OpenJS.NodeJS.LTS
```

In a new PowerShell, `node --version` should print `v22.12` or higher.

## Part 2: set up the project (once)

### Step 5: get the project

Somewhere to keep it, for example Documents:

```powershell
cd ~\Documents
git clone https://github.com/emily7305/starstep-meter.git
cd starstep-meter
```

If the repository is private, Git opens a GitHub sign-in window the first time. Every command from here on runs in the repo folder unless it says otherwise.

### Step 6: create the virtual environment

```powershell
py -3.11 -m venv .venv
```

### Step 7: activate it

```powershell
.venv\Scripts\Activate.ps1
```

The prompt starts with `(.venv)` once it's active. This has to be done in every new PowerShell window that runs Python for this project.

If PowerShell refuses to run scripts, run this once and activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Step 8: install the Python packages

With `(.venv)` showing:

```powershell
python -m pip install -e ".[dev]"
```

It takes a few minutes and prints a lot.

### Step 9: install the frontend packages

```powershell
cd frontend
npm install
cd ..
```

## Part 3: madmom (optional, but worth it)

Without madmom the beats come from librosa. That works, but with lower confidence, a downbeat that is only a guess, and no way to follow a tempo change, so a song that changes tempo comes out as one tempo. madmom is harder to install, so get everything else working first.

1. Install the Microsoft C++ Build Tools and pick the "Desktop development with C++" workload. madmom compiles parts of itself during the install.
2. With `(.venv)` showing, from the repo folder:

   ```powershell
   python -m pip install -e ".[madmom]"
   ```

   This installs madmom from a pinned git commit, because the release on PyPI doesn't build on current Python. It needs Git from step 1.

3. Check it:

   ```powershell
   python scripts\check_madmom.py
   ```

This hasn't been tried on Windows yet (it works on Linux). If the install fails, the app still runs with librosa, and the header in the page reads `madmom not installed`. If it installs but `check_madmom.py` fails, the header reads `madmom failed to import`, with the error when you hover over it. The beats then come from librosa too, and the report says `librosa fallback`.

## Part 4: start the app and analyze a song (every time)

It takes two PowerShell windows, and both stay open while the app is in use.

### Step 10: the backend, in the first window

```powershell
cd ~\Documents\starstep-meter
.venv\Scripts\Activate.ps1
python -m backend.api
```

### Step 11: the frontend, in the second window

```powershell
cd ~\Documents\starstep-meter\frontend
npm run dev
```

### Step 12: open the page and analyze

Open http://127.0.0.1:5173. The header shows `ffmpeg ok · ffprobe ok · madmom ok` (or `madmom not installed` without Part 3).

Press `choose audio file`, pick a song (mp3, wav, flac, ogg or m4a), and press `analyze`. The pills under the buttons count through `upload`, `decode`, `trim`, `beats`, `snap`, `tempo`, `meter`, `check` and `done`. A 4 minute song takes under a minute with madmom.

If you pick a song that was analyzed before, the page says `this file was analyzed before` and offers `reopen` for each earlier job. That brings back the job with the changes you made to it. `analyze again as a new job` starts over instead.

## Part 5: use the result

When the job is done, the timeline shows the waveform with the beat grid and the tempo segments as bands, and a block called `for your chart` sits above it. The steps below go from that block to a song set up in a chart editor. MikuMikuWorld is the editor the numbers were checked against.

### Step 13: read the `for your chart` block

This block is the part to read first. It says in plain words what a chart editor asks for.

- `bpm` is how many beats there are in one minute. When the speed changes during the song, it says `bpm at the start` and gives the first one.
- `offset` is where the first measure starts in the song, as the number to type into the editor's music offset field. It is usually negative. There are two lines: `if you load the wav made with ffmpeg`, and, only when the original file has padding at its start (an mp3 does), `if you load the original mp3`. Step 17 says which one to use.
- `time signature` is how many beats there are in one measure. `4/4` is four.
- The `?` next to each of the three opens a one line explanation.
- If the song changes speed or time signature, a line says so, like `this song changes speed 3 times`, with a `see every change` link to the list in step 16.
- If parts of the song were hard to read, the block says `parts of this song were hard to read, check the shaded areas`. The shaded areas are on the timeline, marked `low confidence`.
- `more decimals` shows the bpm with 4 decimals instead of 2, and `copy` copies the block as text.

For a song with one steady tempo and no warning, this block and step 17 are all there is to do. For anything else, go through steps 14 to 16 first.

### Step 14: check the grid by ear

The thin lines on the waveform are the beats, and the mint ones are the start of each measure. The numbers along the top are the measure numbers. They start at 0 on the first measure line in the audio.

1. Press `play`, and then `click track` next to it. The click track plays a click on every beat and a higher, louder click on every measure line.
2. Listen against the song. The clicks should land on the beats you hear. Two sounds a few milliseconds apart (a flam) mean the grid is slightly off there.
3. Click the waveform where something sounds off. The zoomed view under the play time shows a few milliseconds of the sound around the nearest beat, with the grid line over it. The `40 ms`, `120 ms` and `400 ms` buttons set how wide it is. The line under it, like `tracked 944.068 ms · grid +7.170 ms`, says how far the grid line is from the beat the tracker found.
4. Under the play time, a line like `playhead −42.0 ms output latency` says how far behind the sound the moving line is drawn, because the sound takes a moment to reach the speakers. On Bluetooth headphones the sound arrives even later than that, so judge the playhead with wired headphones. The clicks and the song are always together, whatever the headphones.

### Step 15: fix what is wrong (optional)

Click the band of the segment to fix, and use the panel for that segment (the panel with `segment 1 of 2` at the top, on the right of the page in a wide window).

- If the tempo is half or double what it should be, press `×2` or `÷2`.
- If the grid is a little early or late, press `−1 ms` or `+1 ms` to move it, or click the timeline and press ← and →. The change is saved about half a second after the last step, and `saved` appears.
- If the song really changes tempo in the middle, `split here` splits the segment at the beat shown in the zoomed view.
- The `meter 1 of 2` panel under the zoomed view sets the time signature by hand with `set meter`.
- The `notation suggestions` list offers a half time, double time or fold into neighbour reading of a stretch. `apply` takes it, `dismiss` throws it away. Nothing is applied on its own.

Every change appears in the `edits` list in the report column, and `re-analyze` keeps them. The README section "Using it" describes every control.

### Step 16: read the chart setup list

The `chart setup` panel, under the `notation suggestions`, lists everything to type into the editor, in three parts:

- `music offset` has the same two offsets as the block in step 13, with a note on where measure 0 starts in the audio file.
- `audio file` has the ffmpeg command for step 17 and a `copy command` button.
- `bpm and time signature changes, in order` has one row per change, like `m.24 · 150.00 bpm` or `m.37 · 3/4`. The `m.` number is the measure, counted from 0 like the numbers on the timeline. A row marked `mid-measure` does not start on a measure line, and it says where inside the measure it goes, like `beat 3`, where `beat 1` is the measure line. Clicking a row jumps the timeline to that change.

`copy list` copies the two offsets and every row as text.

### Step 17: make the wav and type the numbers into the editor

Convert the song to a wav first. ffmpeg leaves out the padding at the start of an mp3 the same way the analysis does, so the wav lines up with the timeline. The `chart setup` panel shows the command with the song's name filled in, and `copy command` copies it. For `song.mp3` it is:

```powershell
ffmpeg -i "song.mp3" "song.wav"
```

Run it in the folder the song is in. The quotes keep a file name with spaces working. If the song is already a wav, the panel names the new file `song-ffmpeg.wav`, so it doesn't overwrite the original.

1. Load the wav as the song in MikuMikuWorld.
2. Type the offset `with the wav from ffmpeg` into the music offset field. It is minus where measure 0 is in the audio, so a negative number is normal. A positive offset in MikuMikuWorld starts the song later.
3. Add each bpm and time signature change from the list, at its measure, in order.

If you load the original mp3 into the editor instead, use the other offset, `with the original mp3`. An mp3 starts with a little padding that the decoder adds, and MikuMikuWorld plays it, so the song starts a bit later than the analysis hears it. The second offset is the first one moved by that padding, further negative, so the grid lines up again. The two always differ by exactly the padding, and the report column shows it as `decoder padding`.

For example, in MisoilePunch♪ measure 0 is at 62.362 ms, so the offset is `-62.362` ms with the wav. The mp3 has 23.021 ms of padding, so the offset with the mp3 is `-85.382` ms. A wav has no padding, and then both offsets are the same.

The tool never cuts the audio. The offset is what tells the editor where the first measure is in the file.

### Step 18: reopen or delete a job

The page's url ends in `?job=...` from the first analysis on, so a reload brings the same job back with its changes. The `recent` list in the source column lists earlier jobs, newest first, and pressing one reopens it.

Each job in the list has a `delete` button. Pressing it asks `delete this job and its files?`, and pressing `delete` again removes the job, its upload and its decoded audio. `cancel` keeps it. A job that is still waiting or running has no `delete` button until it's done.

### Step 19: stop the app

Press Ctrl + C in each window, then close them.

## Part 6: check that it works

A generated click track has known right answers. In a window with `(.venv)` showing, from the repo folder:

```powershell
python scripts\make_click_track.py click-120.wav --bpm 120 --lead 2
```

Analyze `click-120.wav` in the page. Expected: trim start about 2000 ms, trim end about 21530 ms, one tempo segment at about 120.00 bpm, which the `for your chart` block also shows as 120.00.

Then a track with a tempo change:

```powershell
python scripts\make_click_track.py tempo-check.wav --bpm 150 --beats 128 --lead 0.75 --accent --change 64:200
```

With madmom this comes out as two bands, 150.00 bpm and then 200.00 bpm, with the change at about 26349 ms, and the `for your chart` block reads `bpm at the start` and says the song changes speed once. The librosa fallback can't follow the change. Press `click track` and play to hear the clicks follow the change. The full checks, with their expected values, are in `docs/roadmap.md`.

Don't add the generated audio to git. `*.wav` and `*.mp3` are ignored anyway.

## Part 7: run eval_local.py on your own songs

The thresholds are tuned on generated tracks and three real songs, and this is how more real songs feed back into them. It runs the analysis on every song in a folder and writes a csv of timing numbers. In a window with `(.venv)` showing, from the repo folder:

```powershell
python scripts\eval_local.py "C:\Users\you\Music\charts" --recursive --out eval_local.csv
```

Put the folder in quotes if its path has spaces. `--recursive` also looks in subfolders. It prints one line per song as it goes. On the cloud VM a 4 minute song takes about 50 seconds with madmom, so a big folder takes a while.

The csv has timing numbers only, never audio, and nothing is written next to the songs. The song file names are in it, though, so look it over before pasting it anywhere. The README section "Real songs: eval_local.py" explains every column.

## Troubleshooting

### `ffmpeg`, `node` or `git` is not recognized

The window was opened before the install. Close every PowerShell window and open a new one. If it still fails, sign out and back in, or restart.

### There's no `(.venv)` at the start of the prompt

Run `.venv\Scripts\Activate.ps1` from the repo folder again. Every new window needs it.

### The header says `backend offline`

The backend window from step 10 isn't running, or it stopped with an error. Start it again and read what it printed.

### The header says `ffmpeg missing`, or a job fails with `analysis failed at decode — check that ffmpeg is on PATH`

The backend can't find ffmpeg. Go back to step 3, then start the backend again in a new window.

### The backend stops with an error about the address already being in use

Another backend is still running on port 8000, usually in a window that was left open. Press Ctrl + C there, or close it, and start again.

### The frontend says port 5173 is in use

Vite moves on to the next free port and prints it, for example http://127.0.0.1:5174. Open that one, or close the other frontend window and start again.

### The `for your chart` block shows a warning, or the clicks don't match the song

See steps 14 and 15. The shaded areas on the timeline are where the analysis was least sure, and the cross-check text in the segment panel (like `librosa 7.13 ms apart`) says whether the two beat trackers agreed there.

### Where the uploads went

Each job is a folder under `data\jobs\` in the repo folder, with a copy of the upload, the decoded audio and the json files. The `delete` button in the `recent` list removes a job and its folder (step 18). When the backend starts, it also deletes the folders of jobs that haven't changed for 14 days (`STARSTEP_RETENTION_DAYS` in the README's settings table, 0 keeps them all). Deleting a job's folder by hand, with the backend stopped, removes it from the list in the page too.

## Linux

The same steps with different commands. In a terminal:

```bash
sudo apt install git ffmpeg python3.11 python3.11-venv
git clone https://github.com/emily7305/starstep-meter.git
cd starstep-meter
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Any Python 3.11 or newer works, with `python3.11` replaced by that version. Ubuntu's own `nodejs` is usually older than 22.12, so install Node from nodesource or with nvm, then:

```bash
cd frontend
npm install
cd ..
```

For madmom, the build tools are a C compiler (`sudo apt install build-essential`), then the same `python -m pip install -e ".[madmom]"` and `python scripts/check_madmom.py`.

To run it, the backend in one terminal and the frontend in another:

```bash
source .venv/bin/activate
python -m backend.api
```

```bash
cd frontend
npm run dev
```

Then open http://127.0.0.1:5173 and go on from step 12. The ffmpeg command in step 17 is the same in a terminal. The eval script is `python scripts/eval_local.py ~/Music/charts --recursive`.
