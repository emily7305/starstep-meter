# starstep-meter

Beat, tempo, and meter analysis for rhythm game charting. Personal project.

*✦ star steps, right on the beat ✦*

Milestone 1 runs on your own machine. You upload a song in the browser, and the backend decodes it with ffmpeg, finds where the music starts and ends (the trim), and estimates one constant BPM, which the browser shows as text. A CLI does the same for one file. It does not do the beat offset, tempo changes, meter, sections, waveform, beat grid, click track, or export yet; those are later milestones. The BPM is a single number for the whole file, so it only fits songs with a steady tempo. This is for personal use only. The server binds to 127.0.0.1, there are no accounts or sharing, and exports (when they exist) contain timing data only, never audio. Uploaded audio is kept only in the local `data/` folder.

## Dependencies and licenses

This project's code is licensed under PolyForm Noncommercial 1.0.0 (see `LICENSE`), so it is for noncommercial use only.

madmom is used for beat and downbeat tracking from milestone 2 on. Its code is BSD-licensed, and its pretrained models carry their own CC BY-NC-SA 4.0 terms. This project does not redistribute madmom or its models. Whoever runs the tool installs them separately.

The licenses below were read from the installed packages' own metadata (Python `importlib.metadata`, npm `package.json`) on 2026-10-24.

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

### Pulled in by librosa

These come in through librosa. soxr is LGPL-2.1-or-later, so it is the one to watch.

| Package | Version | License |
|---|---|---|
| scipy | 1.17.1 | BSD-3-Clause |
| numba | 0.68.0 | BSD-2-Clause |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| soxr | 1.1.0 | LGPL-2.1-or-later |

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

madmom is only needed from milestone 2 on:

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
| `STARSTEP_WORKERS` | 1 | Number of analysis workers |

### CLI without the server

The CLI runs the same analysis on one file and prints the report JSON:

```powershell
python -m backend.analysis.cli path\to\song.mp3 -v
```

With `-v`, stage progress and debug numbers go to stderr. `--threshold-db` sets the trim threshold. `--work-dir` keeps the copied original and the decoded WAV in a folder you choose instead of a temp dir.

### Storage

Each job keeps a copy of the upload and the decoded WAV under `data/jobs/<job id>/`. The decoded WAV is mono float32, about 10 MB per minute at 44.1 kHz. Old job folders are not removed automatically yet, so delete them by hand. `data/` is git-ignored.

## Tests

Backend tests run from the repo root:

```bash
python -m pytest
python -m backend.schema.export_schema --check
```

Tests that need ffmpeg are skipped, not failed, when it is missing. Test audio is generated in code and cached in `tests/fixtures/`, which is git-ignored.

Frontend checks run from `frontend`:

```bash
cd frontend
npm test
npm run check:types
npm run build
```

When you change `backend/schema/models.py`:

1. Run `python -m backend.schema.export_schema`.
2. In `frontend`, run `npm run gen:types`.
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

## Docs

- `docs/architecture.md`: how the pieces fit together.
- `docs/decisions.md`: thresholds, measured accuracy, and what broke.
- `docs/schema-changelog.md`: one line per schema change.
