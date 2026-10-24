# Setup guide

This is the long version of the install and running sections of the README, one step at a time, from a Windows machine with nothing installed to the app running in the browser. Windows comes first because it's the main machine for this project. Linux is at the end. If the two ever disagree, the README is the one that gets updated with each milestone.

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

Each prints a few lines of version info. The README describes installing it by hand instead, if winget isn't an option.

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

This hasn't been tried on Windows yet (it works on Linux with Python 3.11). If the install fails, the app still runs with librosa, and the header in the page reads `madmom not installed`. If it installs but `check_madmom.py` fails, the header reads `madmom failed to import`, with the error when you hover over it. The beats then come from librosa too, and the report says "librosa fallback".

## Part 4: start the app (every time)

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

### Step 12: open the page

Open http://127.0.0.1:5173. The header shows `ffmpeg ok · ffprobe ok · madmom ok` (or `madmom not installed` without Part 3).

Press "choose audio file", pick a song, and press "analyze". When the job is done, the timeline shows the waveform, the beat grid and the tempo segments as bands, and the report column on the right has the numbers. The README section "Running" describes the controls for editing segments.

The page's url ends in `?job=...` from then on, so a reload brings the same job back with its edits. The source column lists earlier jobs to reopen, and picking a file that was analyzed before offers to reopen that job before starting a new one.

### Step 13: stop the app

Press Ctrl + C in each window, then close them.

## Part 5: check that it works

A generated click track has known right answers. In a window with `(.venv)` showing, from the repo folder:

```powershell
python scripts\make_click_track.py click-120.wav --bpm 120 --lead 2
```

Analyze `click-120.wav` in the page. Expected: trim start about 2000 ms, trim end about 21530 ms, one tempo segment at about 120.00 bpm.

Then a track with a tempo change:

```powershell
python scripts\make_click_track.py tempo-check.wav --bpm 150 --beats 128 --lead 0.75 --accent --change 64:200
```

With madmom this comes out as two bands, 150.00 bpm and then 200.00 bpm, with the change at about 26349 ms. The librosa fallback can't follow the change. The README has the full checks under "Milestone 1 manual check", "Milestone 2 listening check" and "Milestone 3 listening check".

Don't add the generated audio to git. `*.wav` and `*.mp3` are ignored anyway.

## Part 6: run eval_local.py on your own songs

The thresholds are tuned on generated tracks only, and this is how real songs feed back into them. It runs the analysis on every song in a folder and writes a csv of timing numbers. In a window with `(.venv)` showing, from the repo folder:

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

### The header says `ffmpeg missing`, or a job fails with "analysis failed at decode — check that ffmpeg is on PATH"

The backend can't find ffmpeg. Go back to step 3, then start the backend again in a new window.

### The backend stops with an error about the address already being in use

Another backend is still running on port 8000, usually in a window that was left open. Press Ctrl + C there, or close it, and start again.

### The frontend says port 5173 is in use

Vite moves on to the next free port and prints it, for example http://127.0.0.1:5174. Open that one, or close the other frontend window and start again.

### Where the uploads went

Each job is a folder under `data\jobs\` in the repo folder, with a copy of the upload, the decoded audio and the json files. Nothing is deleted automatically. Deleting a job's folder by hand removes it from the list in the page too.

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

Then open http://127.0.0.1:5173. The eval script is `python scripts/eval_local.py ~/Music/charts --recursive`.
