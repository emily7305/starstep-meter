# decisions

## madmom install (milestone 1 probe)

Tested in the cloud session: Ubuntu 24.04, Python 3.11.17, numpy 2.4.6, scipy 1.17.1.

- `pip install madmom` (PyPI 0.16.1, from 2018) fails before building: its `setup.py` imports Cython but doesn't declare it as a build dependency, so pip's isolated build env has no Cython.
- Installing `numpy` and `Cython` first and then `pip install --no-build-isolation madmom` builds, but `import madmom` fails with `ModuleNotFoundError: No module named 'pkg_resources'` (current setuptools no longer ships it). 0.16.1 also uses numpy aliases that were removed in numpy 1.24, so I stopped there.
- `pip install git+https://github.com/CPJKU/madmom` works: it builds 0.17.dev0 and `scripts/check_madmom.py` runs `DBNDownBeatTrackingProcessor` on a generated 120 BPM click track, finds 23 beats with the right downbeats and a median tempo of 120.00.

So the `madmom` extra in `pyproject.toml` pins that git commit (`27f032e8947204902c675e5e341a3faf5dc86dae`), installed with `pip install -e .[madmom]`. That was checked in a clean venv too.

Not tested yet: Windows. madmom has Cython extensions, so a source build on Windows needs the MSVC Build Tools (the "Desktop development with C++" workload). Python 3.12/3.13 weren't tried either.

One number for milestone 2: on the click track, madmom's beats come out 10 ms before the click onsets (490 ms for a click at 500 ms). It runs at 100 frames per second, so 10 ms is one frame. Onset snapping will have to deal with that.

Nothing in milestone 1 imports madmom. `/api/health` only checks whether it's importable, and the librosa path runs without it.

## decode

`ffmpeg -nostdin -hide_banner -loglevel error -y -i <in> -map 0:a:0 -vn -ac 1 -c:a pcm_f32le decoded.wav`

- No `-ar`. The sample rate stays native (44.1 or 48 kHz) and is read back from the decoded file with soundfile, not taken from ffprobe on the original.
- `-map 0:a:0 -vn` takes the first audio stream and ignores embedded cover art.
- Mono float32 is all the analysis needs. Stereo is downmixed by ffmpeg's `-ac 1` (channel average).
- Ingest doesn't trust the extension. The extension has to be one of mp3/wav/flac/ogg/m4a so a wrong file gets a fast 415, but ffprobe also has to report one of those containers with at least one audio stream. The upload limit is 100 MB by default.

## encoder delay (open question for milestone 2)

I measured this on the synthetic click track by cross-correlating the decoded audio against the generated samples:

| encode | decoded by ffmpeg | decoder ignores the delay info |
| --- | --- | --- |
| mp3, libmp3lame 192k CBR or V2, with LAME header | 0 samples | +1105 samples (25.06 ms at 44.1 kHz, 23.02 ms at 48 kHz) |
| mp3 written with `-write_xing 0` (no LAME header) | +1105 samples | +1105 samples |
| m4a, ffmpeg aac 192k | 0 samples (edit list honoured) | +1024 samples (23.22 ms at 44.1 kHz) |
| ogg, libvorbis q5 | 0 samples | +128 samples (2.90 ms at 44.1 kHz) |

"Ignores the delay info" is ffmpeg with `-flags2 +skip_manual` (and `-ignore_editlist 1` for m4a). That roughly simulates a game engine whose decoder doesn't read the LAME/iTunes gapless metadata.

So ffmpeg's timeline matches the original PCM. A game that decodes the same mp3 with a different decoder can be about 25 ms late, which is bigger than the whole 10–20 ms offset target. The offset convention in milestone 2 has to say which timeline `beat_offset_ms` is on (I lean towards "ffmpeg's decoded timeline" plus an optional per-game correction at export), and the report probably needs to record the codec and whether gapless info was present. Not solved here.

ffmpeg's aac also leaves padding at the end (+663 samples at 44.1 kHz, +32 at 48 kHz), so `duration_ms` for m4a is a little long. Trim ignores that because the padding is silent.

Settled in milestone 2, see the next section.

## beat offset convention (milestone 2)

Decided before writing the beat code. The main target is Sonolus.

`beat_offset_ms` is the time of the first downbeat, in milliseconds, measured on the ffmpeg-decoded timeline from the first sample of the decoded audio. It is not relative to `trim.start_ms`. It's the same timeline every other time in the report uses, so the waveform, the trim points and the grid all line up without conversions.

The value is the fitted time of the first downbeat, which is the intercept of the beat grid regression at the first downbeat's index, not the raw tracker output for that beat. If there are pickup beats before the first downbeat, the offset still points at the downbeat, not at the pickup.

No compensation for any particular player goes into `beat_offset_ms`. A game whose decoder ignores the gapless info plays the audio late by the decoder padding (25 ms for a typical mp3), but that correction depends on the player, so it belongs in export (milestone 5). The report only records what export needs to make that call:

- `source.codec`: the codec name ffprobe reports for the first audio stream (`mp3`, `aac`, `vorbis`, `opus`, `flac`, `pcm_s16le`, ...).
- `source.decoder_padding_samples`: how many samples a decoder that ignores gapless info would play before ffmpeg's first sample. It's in samples at the decoded sample rate, and 0 when it doesn't apply.

A target that wants the offset inside the first bar (some chart formats do) can wrap it modulo one bar length at export. The stored value stays the real time of the first downbeat, so nothing is lost and the wrap can always be redone.

How the padding is read: ffprobe on the first two packets of the first audio stream (`-show_packets -read_intervals %+#2`). ffmpeg drops the leading samples in one of two ways. It either puts a `Skip Samples` side data entry on the first packet, or it gives the first packet a negative pts, and some codecs do both. The padding is the larger of `skip_samples` and the negative first pts converted to samples. Measured on the synthetic click track against an ffmpeg decode with `-flags2 +skip_manual` (plus `-ignore_editlist 1` for m4a), which stands in for a decoder that ignores the gapless info:

| file | first packet | `decoder_padding_samples` | naive decode lag (cross-correlation) |
| --- | --- | --- | --- |
| mp3, libmp3lame 192k with LAME header | pts 0, skip 1105 | 1105 | 1105 |
| mp3 with `-write_xing 0` | pts 0, no skip | 0 | 0 |
| m4a, ffmpeg aac 192k | pts -1024, skip 1024 | 1024 | 1024 |
| ogg, libvorbis q5 | pts -128, no skip | 128 | 128 |
| ogg, libopus 128k at 48 kHz | pts -312, skip 312 | 312 | 312 |
| flac, wav | pts 0, no skip | 0 | 0 |

An mp3 without a LAME header reports 0 even though it does carry encoder delay. ffmpeg can't see the delay either, so ffmpeg and a naive decoder agree, and the beat offset measured on ffmpeg's timeline is already what that player hears. The padding field is about the gap between ffmpeg and a naive decoder, not about the encoder delay itself.

The tempo map's first segment keeps `start_ms = trim.start_ms` as in milestone 1. The grid phase comes only from `beat_offset_ms`, so editing the offset never has to touch the tempo map, and the two edits don't get coupled.

Changed in milestone 3: `beat_offset_ms` moved into the tempo map as each segment's `anchor_ms`, so the first downbeat is now `tempo_map[0].anchor_ms`. The timeline and the no-compensation rule above still hold for every anchor. See "tempo map (milestone 3)" for why.

Bars in the beats file: the first downbeat starts a bar. Beats before it (a pickup) are bar 0, as a pickup bar usually is in a score, and then the first downbeat is bar 1. Without a pickup, the first downbeat is bar 0.

## trim

RMS on 20 ms windows with a 5 ms hop. The threshold is -60 dB relative to the loudest window, not an absolute dBFS value, so quiet and loud masters trim the same way. The threshold is configurable (`--threshold-db` on the CLI, `STARSTEP_TRIM_THRESHOLD_DB` for the server).

A 20 ms window crossing the threshold only tells you the edge is somewhere in those 20 ms. So each edge is redone with 1 ms windows at every sample (a cumulative sum of squares, so it's cheap) and reported at the centre of the first or last loud 1 ms window. Sound from the very first sample reports exactly 0.0.

What broke: the first version of the fine pass took the first 1 ms window above the threshold anywhere near the coarse edge. With a noise floor only 2 dB under the threshold, single 1 ms noise windows crossed it, and the start came out up to 34 ms early. Now the fine pass anchors on the loudest 1 ms window inside the first loud 20 ms frame and walks back to where that loud run starts. A noise blip that isn't connected to the music can't pull the edge anymore.

Why -60 dB: it's low enough to keep quiet fade-ins and reverb tails, and above dither and the usual noise floor of a mastered track. That's tuned on synthetic clicks only. Real songs with long fades might want -50, and I'll check on real tracks in milestone 2. It needs the noise floor at least a couple of dB below the threshold, and a noisy recording with its floor above -60 dB relative to the peak just trims to the whole file.

Measured on the synthetic tests (clicks peak around -18 dBFS RMS, so the threshold sits near -78 dBFS):

- WAV input, 44.1 and 48 kHz, four padding combinations, eight noise seeds, digital silence and noise floors of -90, -84, -81 and -80 dBFS: start error -0.73 to +0.50 ms, end error -0.50 to +0.48 ms.
- flac through ffmpeg: identical to WAV.
- mp3 192k CBR: start -0.8 ms, end +0.4 ms. mp3 V2 with a -90 dBFS noise floor: start up to -7.4 ms. This isn't a timing shift (the cross-correlation lag is 0), it's mp3 pre-echo putting a little energy before each transient, which the threshold catches. The mp3 trim test uses a ±15 ms tolerance because of this. flac and wav use ±10 ms.
- vorbis q5: start about -3 ms, end about +3 ms. aac 192k: start -1 to -4 ms. Same pre-echo story.

## tempo (milestone 1 placeholder)

Replaced in milestone 2 by the beat grid fit below. `estimate_tempo` stays because the librosa fallback passes its octave-checked bpm to `librosa.beat.beat_track`, which slips to half tempo on fast songs when it guesses by itself.

This is a coarse estimate. Milestone 2 replaces it with a linear regression over tracked beats, and that's where the two-decimal BPM target actually gets tested. It only runs on the trimmed region.

1. Onset strength envelope with `librosa.onset.onset_strength`, hop of 256 samples at 44.1 kHz (5.8 ms per frame). The hop is scaled with the sample rate (279 at 48 kHz) so frames are the same length in ms.
2. `librosa.feature.tempo` for a first guess. It's in `librosa.feature` in 0.10+, and the old `librosa.beat.tempo` alias is deprecated.
3. Octave check. Take the guess, half of it and double of it, keep the ones in 60–240 BPM, and look up the autocorrelation of the onset envelope at each one's beat period. A click on every beat also lines up at 2 and 4 beats, so slower octaves always look supported. The fastest candidate whose peak is at least half the strongest peak wins.
4. Refinement. librosa's tempo bins are whole frame lags, about 1.4 BPM apart at 120 BPM and 2.9 BPM apart at 174 with this hop, which alone can miss ±1 BPM. So the code finds the autocorrelation peak at 1, 2, 3, ... up to 32 beat periods (or half the envelope), interpolates each one parabolically, and fits lag = k × period through all of them. The autocorrelation is divided by its overlap count first, so long lags aren't biased short. If the refinement moves more than 3% away from the octave pick, it falls back to the pick.

Measured on synthetic click tracks (40 beats, 15 tempos from 60 to 233.3 BPM, 44.1 and 48 kHz, plain, -90 dBFS noise, and accented downbeats): the worst error is 0.017 BPM and there are no octave errors. librosa's raw estimate on the same tracks reported half tempo for 174 BPM and up at 44.1 kHz, and for 160 and 180 and up at 48 kHz. It was up to 0.99 BPM off on the rest. So the octave check and refinement are doing real work.

Known limits: click tracks are the easy case. Real music with strong eighth notes will push the octave check towards double time, and swing or tempo drift isn't handled at all. 60–240 is a guess at a sane range for charts, and songs above 240 will come out at half tempo. `confidence` stays null until there's something meaningful to put there.

Changed in milestone 3: the range is 60–320 and the candidates include thirds and 3:2, see "tempo range and half or double (milestone 3)".

## ui direction

Soft and pastel, a little cutecore, but restrained. It should feel like a well-made rhythm game editor, not a landing page. The timeline is the hero. It's a full-width band at the top, empty in milestone 1, and everything else sits underneath it.

Palette (CSS custom properties in `frontend/src/styles.css`):

- `--bg #f4f0f4`: very pale cool pink-gray. It's cool on purpose, because warm off-whites read as beige.
- `--bg-sunk #ebe4ec`: the timeline well and the raw JSON block.
- `--ink #3b1f3f`: deep plum for text. It's softer than black but still has strong contrast on the background.
- `--ink-soft #6f5a73`, `--ink-faint #a796a9`, `--line #dccfdc`: labels, ticks, hairlines.
- `--accent #e0136f`: the one saturated pink. It's only for the playhead, selection, and the primary action, so it always means "this is where you are / what you do next". It's this shade rather than a lighter pink so white button text passes contrast (about 4.7:1).
- `--mint #3cc2a4`: reserved for downbeats on the beat grid later, and unused until then. It's the only cool accent, so downbeats will stand out from the pink playhead.
- `--danger #a3123f`: errors. It's a deep crimson so it doesn't get confused with the accent.

Fonts, self-hosted through `@fontsource` packages (no font CDN):

- M PLUS Rounded 1c for headings, labels and body. It's rounded and friendly without being a novelty face. Only the latin subsets are imported for now, because the full fontsource package is about 42 MB across the four weights. If Japanese song titles start showing up in the rounded face, switch the imports in `main.tsx` to the full set (the browser only downloads the unicode ranges a page actually uses).
- IBM Plex Mono for every number, filename, hash and the JSON. It has no Japanese glyphs, so a Japanese filename falls back to a system font. Timing values are always mono, right-aligned, with tabular figures and units (`2000.0 ms`, `120.00 bpm`), so columns of numbers line up and are easy to compare.

Not used, on purpose: beige or cream backgrounds, orange, serif headings, gradients, glass effects, card grids, icon badges, the Vite starter look, the default Tailwind palette, and Inter/system-ui as the main face. Layout separation is hairlines and whitespace, not boxes.

Copy is tool copy: lowercase labels, no exclamation marks. Stage names show as `decoding`, `trimming`, `estimating tempo`, and failures read like `analysis failed at decode — check that ffmpeg is on PATH`.

## jobs and api

- Jobs run on a `ThreadPoolExecutor` with one worker by default (`STARSTEP_WORKERS`). Analysis is CPU-bound and it's one person uploading, so a queue of one is fine. There's no Celery, Redis or database.
- Each job's state lives in `data/jobs/<id>/status.json`, written atomically (temp file plus `os.replace`, retried briefly on Windows `PermissionError`). The report is written before the status flips to done, so done never shows without a report to fetch.
- After a restart, finished jobs are still served. Jobs that were queued or running are marked failed with "server restarted before the job finished". Re-queueing queued jobs would be nicer and is a todo.
- Ingest runs inside the upload request, not as a job stage. A wrong extension or a file ffprobe can't read gets a 415, a missing ffprobe gets a 503, and nothing is left on disk.
- Upload size: FastAPI parses the multipart body before the route function runs, so a check inside the route would only fire after the whole file was spooled. A small custom route class checks `Content-Length` first and returns 413 when it's over the limit by more than 64 KiB of multipart slack. The byte count in ingest catches anything closer to the limit.
- The server binds to 127.0.0.1. `--host` with anything else prints a warning. There's no CORS middleware because the Vite dev server proxies `/api`.
- Job ids are `uuid4().hex` and are checked against `^[0-9a-f]{32}$` before they're used in a path.

## beat tracking (milestone 2)

madmom's `RNNDownBeatProcessor` plus `DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)`, run on the trimmed region with 0.5 s of padding on each side. Beats more than 50 ms before the trim start or after the trim end are dropped. The tracker can only put a beat out there by guessing, because the padding is below the trim threshold.

- madmom treats a numpy array's sample rate as a label and never resamples it, and its networks were trained at 44.1 kHz. So 48 kHz audio is resampled to 44.1 kHz with soxr (linear phase, so no time shift) before tracking. Beat times come back in seconds, so nothing else changes.
- The DBN's tempo range is 55–240 bpm. madmom's default upper limit is 215, which would halve the faster rhythm game songs. 230 bpm clicks track correctly with the higher limit. (Milestone 3 made it 60–320 for every tempo path.)
- Downbeats need something to find. On clicks where every beat sounds the same, madmom picks an arbitrary beat as beat 1, which is correct behaviour. The accuracy tests use accented downbeats, and `make_click_track.py --accent` makes them for the manual check.
- If madmom isn't installed, or is installed but fails to import (the PyPI 0.16.1 build does that), `auto` falls back to librosa. Asking for `--tracker madmom` by name turns either case into an error instead.
- The librosa fallback is `librosa.beat.beat_track` on the milestone 1 onset envelope with the milestone 1 bpm. It has no downbeats, so the first beat is taken as beat 1 of a 4/4 bar, and bar positions are counted on the fitted grid so a dropped beat doesn't slip the bar. The beats file says `tracker: "librosa"` and the confidence is halved.

Raw tracker error against the click onsets, before snapping: madmom −6.4 to −17.6 ms (mean about −11), librosa +4.3 to +12.3 ms. madmom's beats are 10 ms quantized and come in about one frame early, which matches what milestone 1 saw.

Speed: madmom takes about 3 s for 20 s of audio on this cloud VM (4 cores). A 4 minute click track runs the whole CLI in 36 s, and nearly all of that is the network.

In milestone 3 the same kind of 4 minute run took about 52 s. Profiled in milestone 3b on a 4 minute click track (174 bpm, 696 beats), stage by stage:

| stage | time |
| --- | --- |
| decode and trim | 2.2 s |
| madmom network (`RNNDownBeatProcessor`) | 29.9 s |
| madmom DBN, `num_tempi=None` | 9.3 s |
| madmom DBN, `num_tempi=60` (for comparison) | 2.3 s |
| rough tempo map, octave check, snap, final tempo map | 0.4 s |

The whole CLI took 41 s that time. The octave check is 0.26 s of it, so the milestone 3 slowdown is the DBN's tempo states, about 7 s. The rest of the gap to 52 s was load on the VM, not the code. Fewer tempo states is what made a 3/4 click track come out in 4/4 (see "tempo range and half or double"), so the DBN stays as it is.

There's no easy win in the network either. madmom can run its 8 networks in parallel (`num_threads`), and on 4 cores that was 2.9 times faster, but it does it with a `multiprocessing.Pool` that is created with the processor and never closed. In the server that means a leaked pool per job, or one long-lived pool forked from a threaded process, and on Windows it spawns fresh interpreters. Running the networks on a thread pool instead was 6 times slower, since they're small matrix products in a Python loop and hold the GIL. Left as it is.

## onset snap (milestone 2)

For each tracked beat, compute a spectral flux only around that beat and move the beat to the nearest strong flux peak within ±20 ms. If there isn't one, keep the raw beat. The window is `--snap-window-ms` on the CLI and `STARSTEP_SNAP_WINDOW_MS` for the server.

- The FFT window is 256 samples at 44.1 kHz (5.8 ms), scaled with the sample rate, and the hop is 1/8 of it (0.73 ms) with parabolic interpolation on the peak. Computing it locally keeps it cheap. A 0.7 ms hop over a whole 4 minute song would be about 170 MB of spectrogram.
- The flux is on linear magnitude, credited to the later of the two frames it compares. I measured the variants on jittered beats over wav, mp3 and aac at both sample rates. The mean bias was −0.46 ms with a 4 ms window, −0.77 ms with 5.8 ms and −1.66 ms with 11.6 ms. Adding log compression (`log1p(γ·|X|)`) made each one 0.6 to 2 ms earlier. The spread was under 0.2 ms in every case. 5.8 ms is a compromise. Shorter sits closer to the attack, but on real mixes I'd expect it to get noisy. Revisit with real songs.
- Strong means at least half of the biggest peak in that beat's window, and nearest means nearest to the raw beat. A window whose biggest peak is under 20% of the median over all beats counts as having no onset, which covers a beat in a quiet passage or in silence. Both thresholds are tuned on clicks only.
- The bias is not corrected. On sharp attacks it's a steady −0.73 ms, but it depends on how fast the attack rises, so a constant correction tuned on clicks would be wrong for everything else.

Snapped beats land −0.71 to −0.77 ms from the click onsets, for both trackers, all codecs and both sample rates. So snapping removes madmom's one-frame lead and librosa's late bias alike.

One thing to watch: madmom's worst raw beat was 17.6 ms early, which is only 2.4 ms inside the 20 ms window. If real songs push it further, the snap would miss the attack or catch an earlier one. Centering the window on the raw beat plus one frame would buy margin, but I want to see real songs first.

Done in milestone 3 with the measured bias instead of one frame, see "madmom bias before snap (milestone 3)".

## tempo fit (milestone 2)

`time_ms = offset_ms + period_ms × index`, least squares over the snapped beats in the trimmed region. Time is regressed on the beat index rather than the other way round, because the index is exact and all the noise is in the times. The slope is the beat period (bpm = 60000 / period), and with index 0 on the first downbeat the intercept is `beat_offset_ms`. This replaces the milestone 1 tempo estimate.

Assigning indices is the part that broke. The first version stepped through the beats and added `round(gap / median gap)` each time, which survives a missed beat but not two displaced beats next to each other. A 0.66-period gap followed by a 1.55-period gap became 1 + 2 instead of 1 + 1, every later beat was one index off, and the fit landed 130 ms out on a 550 beat list. Rounding `(t − t0) / period` globally doesn't work either with only the median gap to go on, because 0.5% of period error puts the index a whole beat out after about 100 beats. So now:

1. Start with the median gap as the period and the circular mean phase of the first 16 beats as the intercept. The first beat could be an outlier itself.
2. Fit the first 16 beats, then double the span and fit again, rounding indices against the current line each time. Each fit is precise enough for twice its span.
3. Over all beats, refit until the inlier set stops changing (at most 5 rounds). A beat is an outlier when it's further than max(15 ms, 4 × 1.4826 × MAD) from the line. If two beats round to the same index, only the closer one stays.

Residuals (snapped time minus the fitted grid) are stored for every beat in the beats file, outliers included. `confidence` is the share of beats within 10 ms of the grid, halved for librosa. It's 1.0 on clean clicks, 0.985 with three doubled beats in 200, and about 0.05 to 0.17 on random times. It's meant to drop when a song doesn't fit one steady tempo, which is exactly what a later tempo-change milestone needs to detect. The 10 ms tolerance is a guess.

On 300 random synthetic beat lists (70–230 bpm, 30–600 beats, σ = 2 ms, 5% dropped beats, 3% displaced by 30 ms to 0.4 period, up to 3 pickup beats), every index came out right. The worst bpm error was 0.015, on 33 to 84 beat lists at over 200 bpm. That's the noise limit (σ·√12/n^1.5 for the period), not a fit problem. The worst offset error was 0.9 ms.

## measured accuracy (milestone 2)

Whole pipeline (ffmpeg decode, trim, track, snap, fit) on accented click tracks, ground truth from the generator:

- The test suite covers 10 cases with madmom and 2 with librosa: 87.5–200 bpm, offsets including 137.5, 1234.567, 87.5, 2003.25 and 41.3 ms, 3/4, a −90 dBFS noise floor, mp3 at 44.1 and 48 kHz, and m4a. The worst offset error is 0.75 ms and the worst bpm error 0.0002 (the 4 decimal rounding). The test tolerances are 5 ms and 0.01 bpm.
- A random sweep of 22 runs over both trackers (80–230 bpm, offsets 20–2500 ms, wav, mp3 CBR and V2, aac, vorbis, 44.1 and 48 kHz) gave offset errors between −0.72 and −0.75 ms and bpm errors of at most 0.0002.
- With two pickup clicks, the offset still points at the first downbeat, and the pickups get indices −2 and −1 and bar 0.

Click tracks are the easy case. Real music has soft attacks, swing, and tempo drift, and none of that is tested yet.

## timeline, beat grid and offset editing (milestone 2)

The waveform is wavesurfer.js 7.12. 8.0 came out a month ago as a new major, and 7.x has the plugin API I know works. It loads the decoded wav from `GET /api/jobs/{id}/audio`, the same file the analysis ran on, so the waveform, the grid and every number in the report share one timeline. The browser decodes it with WebAudio and may resample it to the audio context's rate for drawing, but times go through the buffer's own rate, so that doesn't move anything.

The beat grid is a wavesurfer plugin (`beatGridPlugin.ts`) with a canvas that only covers the visible part of the waveform and follows the scroll. A whole song zoomed to 2000 px/s is about 480,000 px wide, far past what a canvas can be. Lines come from `beat_offset_ms`, the bpm and the bar length, not from the tracked beats, so an offset edit moves the whole grid. The bar length is the most common full bar in the beats file (4 if there isn't one). Bar lines are 2 device px in `--mint`, and beat lines are 1 device px in the waveform colour at 55% alpha. Below 5 px between beats, only bar lines are drawn, and below 5 px between bars, every 2nd, 4th... bar. All the time-to-pixel maths is in `grid.ts` as plain functions, tested at fit, 200 and 2000 px/s.

Fine work happens in the zoomed view under the waveform (`Loupe.tsx`, a canvas drawn straight from the decoded buffer). It's 40, 120 or 400 ms wide, centred on a tracked beat: the first downbeat when the file loads, then the tracked beat nearest wherever the waveform is clicked. The centre stays put while the offset changes, so the grid line visibly slides over the attack in 1 ms steps (about 7 px per ms at 120 ms wide). It also shows a ms scale, the tracked beats as small markers, and how far the nearest grid line is from the tracked beat.

Offset edits:

- ← and → move the offset by 1 ms while the timeline area has focus, and so do the −1 ms / +1 ms buttons. Space plays and pauses when the waveform itself has focus.
- The new value is sent with `PATCH /api/jobs/{id}/report` once it has sat still for 500 ms, so holding an arrow key down becomes one edit (old → new) instead of one per millisecond. Every value the server receives is logged in `edits`, and nothing that only lived on screen is. Only one patch is in flight at a time, always with the newest value, and a value that ends up back where the server already is never gets sent.
- The edit shows up in the list straight away (the same entry the server will append), and the server's report replaces it when the patch returns. A failed patch puts the old report back and says `save failed — <reason>` with a retry.
- The server keeps one lock around every report read-modify-write, so a burst of patches can't read the same old report and drop an edit. The API test sends 20 at once and checks that the old → new chain is unbroken.
- Two things the API tests caught. NaN or Infinity in the body gave a 500, because FastAPI's 422 body echoes the input and a NaN can't be written as JSON. The 422 handler now leaves the input out. A numeric string like `"2100"` was also accepted through pydantic's lax mode, so the field is strict now.

Japanese song titles: `@fontsource/m-plus-rounded-1c/400.css` splits the Japanese glyphs into about 120 slices, each with a `unicode-range`. The CSS for that is 144 KB, so it's a dynamic import (`fonts.ts`) that only runs once a filename has kana, kanji or fullwidth characters in it, and the first paint only loads the 10 KB main stylesheet. Then the browser only downloads the slices it needs (4 woff2 files, a few KB each, for a title of 11 Japanese characters). `japanese-400.css` would have been the wrong file, because it's one 900 KB font with no `unicode-range`. M PLUS Rounded 1c is also second in the mono stack, because IBM Plex Mono has no Japanese and filenames are set in mono. Checked in Chromium with Playwright: `CSS.getPlatformFontsForNode` on the picker, the report row and the timeline title reports 11 glyphs in "Rounded Mplus 1c" (the bundled face, not a system font) and 9 in IBM Plex Mono. Only weight 400 is loaded for Japanese, since filenames only ever show at that weight.

## madmom bias before snap (milestone 3)

madmom's raw beats are shifted by its median bias before the snap search, and the window stays at ±20 ms. `MADMOM_BIAS_MS` is −11.8, so every madmom beat moves 11.8 ms later before snapping. A beat that finds no onset keeps the shifted time, which is a better guess than the raw one.

How it was measured: 48 accented click tracks with a random bpm between 70 and 300, a random lead between 0.05 and 2.5 s, half at 44.1 kHz and half at 48 kHz, every fifth in 3/4. madmom with the 60–320 range, the octave check applied, and beats the octave check inserted left out because they aren't tracker output. The error is the raw beat minus the nearest click onset, over 2480 beats. Median −11.83 ms, mean −11.89, 1st percentile −17.18, 99th −6.52, worst −18.15 and −3.74. After the shift the spread is about −6 to +8 ms, so there are 12 ms of margin left on both sides of the window.

What went wrong first: the first run said −10.46. It used round tempos (80, 120, 150, 200 bpm) whose period is a whole number of 10 ms frames, and the region handed to madmom starts 0.5 s before the first click, so every click sat at the same frame phase and those tracks gave −10.45 on every beat. Real songs land at any phase, so the second run picks the bpm and lead at random.

librosa's bias (+4.3 to +12.3 ms late, from milestone 2) isn't shifted. It's already well inside the window.

The test feeds beats 18 to 25 ms early through the snap and through the whole pipeline (with the tracker swapped out). They all snap within 1.5 ms of the click. Without the shift, beats 21 to 25 ms early don't snap at all. A wider window would also have caught them, but on busy songs it can grab the wrong onset, so the window stays at 20.

The eval script's `median_snap_move_ms` column is the move from the raw tracker beat to where it snapped, with the bias shift included. If the bias holds on real songs, it sits near +11 ms over a folder (the 11.8 ms shift, less the 0.7 ms snapped beats land before an attack). One song alone can be off by up to about 5 ms either way, depending on where madmom's 10 ms frames fall, and the 120 bpm click track in the milestone 2 check gives +6.8. A folder median far from +11 means the bias needs measuring again on real material.

## tempo range and half or double (milestone 3)

Every tempo path takes one `TempoRange`, 60–320 bpm by default. That covers the milestone 1 estimate the librosa fallback runs on, madmom's DBN, and the octave check below. It is set in `backend/analysis/tempo_range.py`, and can be changed with `--min-bpm`/`--max-bpm` on the CLI and the eval script, or `STARSTEP_MIN_BPM`/`STARSTEP_MAX_BPM` for the server. The hands-on case was a 270 bpm song that came out at 135.51 with the old 240 ceiling.

Raising the ceiling wasn't enough on its own. What broke and how it was fixed:

- madmom still tracked accented 250, 270 and 300 bpm click tracks at half tempo for some leads. It isn't the DBN, it's the network. Its beat activation on every other click is about 0.2 against 0.6 on the others, so it hears half time. Plain clicks without accents came out right.
- The milestone 1 estimate gave 90 for 270 bpm clicks. librosa's coarse guess leans towards 120 and landed on a third, and the octave check only looked at half and double. It now also tries 1/3, 2/3, 3/2 and 3 times the guess. The rule is unchanged: the fastest candidate whose autocorrelation peak is at least half the strongest wins.
- With 60 log-spaced tempo states over 60–320, one 3/4 click track came out in 4/4. `num_tempi=None` keeps every whole-frame beat interval (82 states at 100 fps) and costs the same time.
- A track at 128, then 192, then 128 bpm came out as 128, 96, 128. madmom followed the middle part at half tempo, and an octave check over the whole song was outvoted by the rest. The check now runs on each rough tempo segment, found from the raw beats first.

How the choice is made now. `backend/analysis/octave.py` looks at onset strength, the same short-window spectral flux the snap uses, on linear magnitude. It is read in three places: on the tracked beats, halfway between them, and on every other beat.

- It halves when one parity of beats is under 0.4 of the other. That parity is offbeats the tracker took for beats.
- It doubles when the midpoints reach 0.8 of the weaker beats (their 25th percentile, so accented downbeats don't hide a real pulse).
- Each happens at most once, and only inside the range. In between, the tracker's choice stands.

Measured on click tracks:

- 87.5 to 230 bpm in 4/4 and 3/4 with both trackers: no octave change.
- 250, 270 and 300 bpm at three leads each: right with both trackers. madmom's half-time picks were doubled back.
- 120 bpm with offbeats at 25% of the beat level: madmom and librosa both said 240, and the check halved it back to 120.
- 135 and 150 bpm with offbeats at 50% and 70%: madmom said 135 and 150, librosa said 270 and 304, and both were left alone. This is the ambiguous zone. At 90%, madmom's 135 and 150 were doubled.
- 170 bpm with offbeats as loud as the beats stays at 170, because 340 is out of range.

Where it's still ambiguous:

- Real songs whose off-beat eighth notes (hats, synth stabs) reach 50 to 80% of the weaker beats' flux. There the answer depends on the tracker, and madmom and librosa can disagree.
- Fast songs where every other beat is much quieter than the rest can still come out at half.
- A song that switches to exactly half or double tempo on a steady beat doesn't show up in the beat times at all if the tracker keeps the old pulse. A 174 to 87 bpm click track came out at 87 throughout.

All of these are what the ×2 and ÷2 buttons per segment are for. The thresholds are tuned on clicks only.

## tempo map (milestone 3)

`backend/analysis/tempo_map.py` splits the snapped beats into segments and fits each with the milestone 2 `fit_grid`, so every segment has its own bpm and its own anchor (its first downbeat, index 0 of its grid).

Why the schema changed. A manual segment has to carry its whole grid. If the phase still came from one global `beat_offset_ms`, re-analysis would recompute it and move a manual segment's grid even though the segment itself was left alone. So each segment got `anchor_ms`, `beat_offset_ms` went away, and the first downbeat is `tempo_map[0].anchor_ms`. Segments also got an explicit `end_ms`. With an implicit end, a manual segment would grow or shrink whenever the auto segment after it was replaced. 1.1 reports are upgraded on read (`backend/schema/migrate.py`), so milestone 2 jobs still open with their edits.

How boundaries are found:

1. Rough beat indices from the gaps, each gap counting round(gap / running median gap) beats.
2. Recursive two-line split. The cut that minimises the squared error of two lines (time against index, both sides at least `min_segment_beats`) is taken whenever the split is justified, or one line can't hold the grid in that range. A split is justified when:
   - the bpm differs by more than `bpm_shift_ratio`, or
   - the phase jumps by more than `residual_shift_ms`, folded onto the nearest whole beat, or
   - one line drifts past `residual_shift_ms` and two lines fix that.

   Each of those also has to be `shift_z` standard errors out, so a short noisy side can't fake one. One line "can't hold the grid" when the running median of its residuals (`smooth_beats` long) goes past `residual_shift_ms`.
3. Merge. Every boundary is checked again against its final neighbours, and the weakest unjustified one is merged until all hold. A middle segment is merged into both its neighbours when the beats either side of it sit on one line together (unfolded). That's a fluctuation the song comes back out of onto the old grid. A real short section at another tempo leaves the grid after it shifted.
4. Each boundary is placed again by the two-line cut between its final neighbours.
5. The beats within two of each boundary are given to whichever line they sit on. Ties go to the new segment, so the bpm change lands on the first beat of the new tempo, where a chart puts it.

A segment after the first starts at its first beat on its own grid. The first starts at `trim.start_ms` and the last ends at `trim.end_ms`.

The thresholds are in `TempoMapConfig`:

| setting | value |
| --- | --- |
| `residual_shift_ms` | 8 |
| `bpm_shift_ratio` | 0.004 |
| `shift_z` | 5 |
| `smooth_beats` | 16 (7 in milestone 3, see milestone 3b below) |
| `min_segment_beats` | 8 |
| `refine_beats` | 2 |

Each has a test that flips its decision. They were tuned on synthetic beat lists and click tracks. The first real song went through in milestone 3b, see "tempo map on a real song" below.

What broke on the way:

- The first version accepted a cut only if that one cut was justified. On a fast-slow-fast song the best single cut leaves one side mixed, nothing passes, and the middle section was missed. Now it splits generously and lets the merge pass decide.
- Splitting generously made a 4-beat wobble its own 9-beat segment, because its slope really is different. That's what the fluctuation merge in step 3 is for.
- The rough-index slip repair (two displaced beats next to each other can make the gap count one beat too many) fired on a mixed range that looked like a 2-beat slip. Now it only repairs ±1, and only if one line fits after the repair.
- With three tempos in one range, the first cut landed between two changes, and the minimum length then forced the next cut 3 beats short of the real change. The boundary refinement only moves 2 beats, so it stayed wrong and then spoiled the line fit for the next boundary. Step 4 fixed that.

Measured on synthetic beat lists:

- 300 random tracks with one or two changes. The bpm was between 70 and 300 with every change at least 3%, each part 32 to 200 beats long, and the jitter up to 3 ms. All had the right number of segments. The worst change point was 0.005 beats off.
- In the same set, the bpm error was 0.0103 at the 95th percentile and 0.0715 at worst. The worst ones are short segments with high jitter, which is the noise limit of a line fit (σ·√12/n^1.5 for the period), not a segmentation problem. Hitting 0.01 bpm needs a segment long enough for that formula.
- 500 random steady tracks (60 to 320 bpm, 32 to 800 beats, jitter up to 4 ms, 2% of beats displaced by up to 18 ms) gave 2 false splits, both with about 3.9 ms jitter at 240 and 316 bpm.
- Pauses of 30 ms and half a beat split. A 6 ms phase step, a 4 beat wobble 12 ms late, a 6 beat rubato, displaced, dropped and doubled beats don't.
- An accelerando from 120 to 126 bpm over 200 beats becomes about 8 steps, and the grid stays within 8 ms.

Measured through the whole pipeline with madmom on click tracks:

- 150 to 200, 174 to 128 (mp3), 128 to 192 to 128, and 140 to 180 to 210 at 48 kHz. Every bpm is right to the 4 decimal rounding, and every change point is within the snap's 0.73 ms of the click. The tests check within one beat and within 5 ms.
- Steady 128 and 270 bpm tracks with 2 ms jitter come out as one segment with both trackers.

Limits:

- A 0.5% step with 2 ms jitter can put the boundary up to 2 beats off. A 0.2% step is only found from the drift it builds up over many beats.
- The librosa fallback can't follow tempo changes at all. `beat_track` runs at one tempo, and its confidence is low on such songs.

## manual tempo edits (milestone 3)

`PATCH /api/jobs/{id}/report` takes one operation: `set_anchor`, `set_bpm`, `split`, `merge` or `match` (milestone 3b). The rules are in `backend/analysis/tempo_edit.py`.

- source `manual` means the user touched the segment, its boundaries or its values, so re-analysis leaves it alone. confidence null means its bpm or anchor was set by hand.
- `set_bpm` keeps the anchor and rebuilds the grid around it, which is what ×2 and ÷2 are. `set_anchor` is the 1 ms nudge from milestone 2 and also "anchor here" (the tracked beat in the zoomed view), which rebuilds the grid from that beat.
- A split of a fitted segment refits both halves from the tracked beats in them. A split of a hand-set segment keeps its grid, and the right half's anchor moves to the first grid line at or after the split, so no line moves and a new bar starts there (the way rhythm game timing points restart bars). A merge of two fitted segments refits the union. If one of the two was set by hand, its grid wins, and if both were, the first's does.
- `match` joins a segment to its previous or next neighbour with the neighbour's bpm and anchor as they are. Nothing is refit, and the result has no confidence, since its extent was set by hand. It's one edit, for a stretch that is the neighbour's tempo felt differently.
- A segment's `ratio_merged` sections are left out of every refit, the way the analysis left them out of its fit. They follow the segment through edits: a split clips them to each side, a merge or match keeps both segments' sections, and a section that ends up covering a whole segment is dropped, since it is that segment now. So splitting at a section's start and end gives it back with its own fitted tempo. The ui's "split out" does exactly that, as two split edits.
- The edit log says exactly what moved. `set_bpm` and `set_anchor` add one entry per changed field of that segment, so the first edit of an auto segment also logs `source` auto → manual and `confidence` → null. Split, merge and match log the whole `tempo_map` before and after.
- Re-analysis (`POST /api/jobs/{id}/reanalyze`) runs the pipeline again on the stored upload. The manual segments come back exactly as they were, and the fresh auto segments fill only the time they don't cover, clipped at their edges. The edit log is kept, and re-analysis itself isn't logged since it isn't a manual change.

A failed re-analysis keeps the last good report (milestone 3b). Before, the job showed as failed and its report wasn't served until a re-analysis succeeded, even though the file on disk was untouched. Now a re-analysis decodes into a `.rerun` folder inside the job, and the decoded wav only replaces the old one once the whole pipeline has run. A failed job that still has a `report.json` serves its report, beats and audio as before, and edits still work on it. `GET /api/jobs/{id}` says so with `report_available`, which is worked out when the status is read and never stored. The ui keeps the report on screen with "re-analysis failed at <stage> — <reason>. showing the last good report". A first analysis that fails has no report and still answers 409. A server restart in the middle of a re-analysis marks the job failed and clears the `.rerun` folder, and the last good report stays available.

## reopening jobs (milestone 3)

Hands-on testing showed manual edits looked lost after a reload, so this moved up from milestone 5.

- The open job's id is in the url (`?job=<id>`), so a reload or back and forward reopens it.
- The source column lists every job from `GET /api/jobs`, newest first, with the file name and date. Any of them can be reopened.
- Before uploading, the browser hashes the file (`crypto.subtle`, which exists on 127.0.0.1 because it counts as a secure context) and asks `GET /api/jobs?sha256=`. If the same file was analyzed before, it offers to reopen that job, with its edit count, before starting a new one. Without `crypto.subtle` the check is skipped and the upload goes ahead.
- No accounts, everything stays in `data/`.

## tempo bands in the ui (milestone 3)

- Segments are drawn on the waveform as bands. Every other one has a faint ink tint, so boundaries read without a line of their own competing with the bar lines. The selected segment gets the accent tint at 9% and a 2 px accent edge along the bottom, since the accent means "where you are".
- Each band has a label in the bottom strip, like `200.00 bpm · manual`, in the mono face. The label stays pinned to the left of the view while its band's start is scrolled off.
- Clicking the waveform selects the segment under the click and puts the nearest tracked beat in the zoomed view. The controls on the right act on the selected segment.
- Bar numbers keep counting across segments, and each later segment's bars start at its anchor.
- Grid lines are thinned per segment, since a 240 bpm stretch crowds before a 120 one.
- A line less than a quarter period before a boundary belongs to the next segment, so a bpm change on a beat draws one line there. The backend refits segments with the same rule.

## health check imports madmom (milestone 3b)

`/api/health` used to say `madmom ok` when the package was installed, without importing it. The PyPI 0.16.1 build installs fine and then fails on import (it wants `pkg_resources`), so the header said ok while every job fell back to librosa. Now `madmom_import_error()` in `backend/analysis/beats.py` imports it once, cached for the life of the process, and the server calls it at startup so the first health check doesn't wait about a second for it. Health reports `madmom: true` only when the import works, plus `madmom_error` with the exception when an installed madmom doesn't import. The header shows `madmom failed to import` with the error in its tooltip, and `madmom not installed` when it isn't there at all. `auto` uses the same cached check to pick the tracker.

## tempo map on a real song (milestone 3b)

The first real song through the tempo map has a chart at a constant 270 bpm, so the right map is one segment at 270.00 from the first downbeat to the end. Its `beats.json` and `report.json` are kept in `tests/real/`, which is git-ignored, and `tests/test_real_song.py` runs the tempo map on them and skips when they're missing. No audio is kept.

Milestone 3 gave it 9 segments:

| start → end (ms) | bpm | what it was |
| --- | --- | --- |
| 119.5 → 3388.1 | 268.56 | intro, the tracker settling in |
| 3388.1 → 5175.1 | 264.37 | same |
| 5175.1 → 44511.1 | 270.02 | |
| 44511.1 → 58727.9 | 202.50 | exactly 3/4 of 270, sounds slower from about 48 s |
| 58727.9 → 81177.6 | 270.05 | |
| 81177.6 → 86281.0 | 270.35 | |
| 86281.0 → 91615.6 | 179.91 | about 2/3 of 270, an unusual rhythm, not a slowdown |
| 91615.6 → 128519.3 | 269.98 | |
| 128519.3 → 134214.0 | 285.38 | the outro fading out |

Now it gives one segment, 119.5 → 134214.0 ms at 270.0038 bpm (558 beats, confidence 0.89), with the two felt sections kept as notes on it: 44510.9 → 58723.7 ms at 202.501 bpm (3/4, fit 1.08) and 86270.2 → 91621.4 ms at 179.909 bpm (2/3, fit 1.00). Three changes got it there.

### residuals that hang together

Three of the boundaries (both in the intro, and the one between 270.05 and 270.35) were the drift test firing on beats that sit off the grid for a few beats at a time. On this song the residuals against one 270 line have a lag-1 autocorrelation of about 0.67, while the tests assumed independent jitter. A fill, or another instrument taking the attack for a bar, moves 3 or 4 beats together, and a 7 beat running median called that a drift.

- `smooth_beats` went from 7 to 16, four bars of 4/4.
- The standard errors in the split test are inflated by √((1 + ρ)/(1 − ρ)), with ρ the lag-1 autocorrelation of that line's residuals, clipped to 0 – 0.9. That is the usual AR(1) correction for the effective number of points. Independent jitter has ρ near 0 and is unaffected.

That alone took the song from 9 segments to 6: 270.02, 202.50, 269.99, 179.91, 269.98 and the 285.38 outro. The milestone 3 measurements still hold with all of milestone 3b in: 300 of 300 random change tracks right with change points within 0.005 beats, and the 120 → 126 accelerando still becomes 8 steps that stay within 8 ms. The steady-track false splits went from 2 of 500 to 0.

### the ratio check

The rest is in a consolidation pass after segmentation (`_Consolidator` in `tempo_map.py`). A segment that is within `ratio_tolerance` (0.5%) of 1/2, 2/3, 3/4, 4/3, 3/2 or 2 of its neighbour's bpm may be the neighbour's tempo felt differently. The neighbour's grid is carried on through it at the same phase, and the question is whether its beats land on that grid's lines, halves, thirds, or 1/numerator of the ratio (quarters for 4/3). A beat counts within `ratio_hit_ms` (10 ms). The score is the share of its beats that land there over the share that land on its own fitted lines. It merges when the score is at least `ratio_fit_min` (0.8) for both neighbours. Otherwise the change stays.

Halves and thirds both count whatever the ratio. A tracker following a 3-3-2 bar puts beats on the 270 grid's halves, where the clicks are, and fills the gaps with guesses of its own. Its own line then catches fewer of its beats than the 270 grid does. With only thirds for a 3/4 ratio, that section scored low and stayed split.

Only a segment with a neighbour on both sides, both longer than it, is a candidate. A felt section sits inside the notated tempo and the song comes back out of it. Without that rule, a modulation from 270 to 202.5 that runs to the end, which is exactly 3/4 and can be phase continuous, was folded into whichever side was longer. Both sides have to carry it, so a section that comes back on a different phase stays split.

The merged section's beats are left out of the fit, so the notated tempo comes only from its own beats. They are measured against the nearest line, half or third, and the section is kept in the report as `ratio_merged` on its segment (schema 2.1), shown in the segment panel with a "split out" button.

Scores:

| case | bpm on its own | ratio | score | result |
| --- | --- | --- | --- | --- |
| real song, 44.5 – 58.7 s | 202.501 | 3/4 | 1.08 | merged |
| real song, 86.3 – 91.6 s | 179.909 | 2/3 | 1.00 | merged |
| clicks, 3-3-2 bars for 32 beats, madmom | 203.36 | 3/4 | 1.10 | merged |
| clicks, 3-3-2 bars for 48 beats, madmom | 202.75 | 3/4 | 0.85 | merged |
| clicks, 3 even clicks per bar for 48 beats, madmom | 202.50 | 3/4 | 1.00 | merged |
| beat list, 3/4 with 3 ms jitter | 202.50 | 3/4 | 1.00 | merged |
| beat list, every other felt beat 15 ms late | 202.45 | 3/4 | 0.50 | split |
| beat list, 0.2% off 3/4, comes back | 202.91 | 3/4 | 0.36 | split |
| beat list, 0.35% off 3/4, comes back | 203.21 | 3/4 | 0.27 | split |
| beat list, 3/4 a quarter beat late, comes back | 202.50 | 3/4 | 0 | split |
| clicks, 270 → 202.5 to the end, madmom | 202.50 | 3/4 | not a candidate | split |

The 48 beat 3-3-2 at 0.85 is the closest call. Each threshold has a test in `tests/test_tempo_map.py` that flips its decision.

### felt sections and the octave check

The octave check runs per rough segment, and the rough map used to come from the same `build_tempo_map` as the final one. Two things went wrong once felt sections were in play.

- With the ratio check on, the rough map folded a half time section into its neighbours, so it never got its own octave check. The rough map now runs with `consolidate=False`.
- A felt section that got its own check could be pushed off every ratio. In the 48 beat 3-3-2 track madmom's beats alternate between a click and a guess, the parity test saw every other beat with no onset, and halved the section to 101.44 bpm, which is 3/8 of 270. A triplet feel section was doubled to 405 in an earlier version.

`felt_sections` marks a rough segment that sits between two others at a dotted or triplet ratio (2/3, 3/4, 4/3, 3/2) of both. The first fix left those as tracked, and that broke the milestone 3 test with 128, 192 and 128 bpm: madmom takes the 192 part at 96, which is 3/4 of 128, so it counted as felt and never got doubled back. Now a felt section's octave change stands when it keeps the section at the same tempo as both neighbours (after their own octave check) or at one of the ratios to them. 96 doubled to 192 is 3/2 of 128 and stands. 202.75 halved to 101.4 is 3/8 of 270 and doesn't. Half and double time sections that aren't felt are the octave check's as before.

### short segments and weak edges

The same pass merges two more kinds of segment.

- Short: under `short_min_ms` (4 s) or `short_min_bars` (8 bars of 4/4, 7.1 s at 270), whichever is longer, and within `short_bpm_ratio` (2%) of a neighbour. It goes into the closer neighbour if that one isn't short itself, and that neighbour keeps its grid. Two short ones only join each other while the result is still short. The first version just joined short segments, and the 120 → 126 accelerando, whose 8 steps are each about 12 s at 120 bpm and so all short, was joined into one line 57 ms off at its ends.
- Weak edge: the first or last segment, shorter than its neighbour, whose beats cover less than `weak_coverage` (0.6) of its span (beats × period over its length), or whose median level is `weak_energy_db` (−12 dB) or more under the song's median. The level comes from 50 ms frames of the decoded audio. It goes into the neighbour, which keeps its grid. The real song's outro has 9 beats over 5.7 s, a coverage of 0.33.

With the 16 beat smoothing the real song doesn't need the short rule any more, so it's tested on a beat list built like the milestone 3 intro (268.56 for 15 beats, 264.37 for 8, then 270).

### the boundary near 48 s

The 202.50 section started at 44511 ms, about 3.5 s before the change that's heard at about 48 s. The beats themselves change there. madmom's beat gaps go from about 222 ms to about 296 ms at 44511 ms, after a 449 ms gap from 44062 ms, and the gaps after 48 s look like the ones between 44.5 and 48 s. So the tempo map put the boundary where the tracked beats change, and there's nothing in the beats that would move it to 48 s. Moving it would mean second-guessing the tracker from the onsets, which I haven't done. On this song it no longer matters, since the section is merged, and "split out" cuts at 44510.9 ms.

### limits

- A modulation at exactly a ratio, phase continuous, that comes back to the first tempo can't be told apart from a felt section. It is merged, and "split out" gives it back.
- A beat list with a beat on every onset of a 3-3-2 bar fits about 186 bpm, which is no ratio of 270, and stays split. Trackers don't output that, they follow a steady pulse, so the realistic cases are the madmom click tracks above.
- The librosa fallback can't follow a felt section any more than a tempo change. A 270 → 202.5 click track comes out as one 67.5 bpm segment with it.
- This is one real song. More will come through `scripts/eval_local.py`.

## tempo follow-ups from five real songs (milestone 3c)

`scripts/eval_local.py` ran on five real songs whose official charts each have one tempo. Three came out right in 3b, as one segment each: きゅうくらりん at 220.0094, I Wanna at 199.9984 and MisoilePunch♪ at 270.0038. ENDYMION came out as 8 segments, and YOUNITHM as one segment with a 95th percentile residual of 110.9 ms. The beats and reports of ENDYMION and YOUNITHM are in `tests/real/endymion/` and `tests/real/younithm/` (git-ignored), next to `tests/real/misoilepunch/`, and `tests/test_real_song.py` runs on all three.

### madmom's bias on real music

`median_snap_move_ms` was 11.6 to 11.9 ms on all five songs (11.915, 11.919, 11.815, 11.587, 11.711). The beats are shifted by 11.8 ms before the snap, so snapped beats land on average within a few tenths of a ms of that shift, and the −11.8 ms measured on clicks in milestone 3 holds on real music too.

### ENDYMION

The pulse is a steady 220 (charted as 440 in 8ths, and as 220 in 16ths in places). 3b gave:

| start → end (ms) | bpm | what it was |
| --- | --- | --- |
| 1143.4 → 6051.8 | 219.42 | the intro at the song's tempo, 11 ms late on average |
| 6051.8 → 13978.3 | 264.32 | 6/5 of 220, madmom on a 227 ms pulse |
| 13978.3 → 88362.2 | 220.00 | |
| 88362.2 → 92572.4 | 215.48 | madmom losing the beat |
| 92572.4 → 95249.1 | 203.41 | same, 24 tracked beats over 25 grid beats |
| 95249.1 → 114338.4 | 219.93 | back on the same grid, 2 ms off |
| 114338.4 → 116775.8 | 292.75 | 4/3 of 220, on the 220 grid's quarters |
| 116775.8 → 122019.4 | 267.87 | the outro |

Now it gives 3 segments: 1143.4 → 114338.4 ms at 219.9965 bpm with the 6/5 section kept as a note, then 292.75 and 267.87 for the last 7.7 s. Four changes got it there.

The ratios are no longer a fixed list. A felt tempo is q/p of the notated one, where its beats land every p steps of 1/q of a notated beat, with q one of `ratio_subdivisions` (1, 2, 3, 4, 6) and p up to 6, within half and double time. That gives 1/2, 3/5, 2/3, 3/4, 4/5, 6/5, 4/3, 3/2 and 2. 1, 2, 3 and 4 alone give back the 3b list. The score is the same as in 3b, the share of the section's beats that land on the extended grid over the share that land on its own lines, with the extended grid's lines, halves, thirds and 1/q (sixths for 6/5).

The score doesn't use every subdivision at once. Lines, halves, thirds, quarters and sixths together catch 59% of random beat times within 10 ms at 220 bpm and 69% at 270, so a modulation that drifts would score as well as a felt section. Lines, halves, thirds and 1/q catch 29 to 54%. ENDYMION's 6/5 section scores 0.81: madmom's beats there wobble about ±15 ms around a 227 ms pulse, so its own lines catch only 47% of them and the 220 grid's sixths 38%. That's the weakest merge so far, and it rests as much on the tempo being within 0.12% of 6/5 as on the phase.

A felt section next to a short first or last segment can fold now. The 264.32 section has the 17 beat intro on one side, shorter than itself, so 3b's rule (both neighbours longer) didn't apply. A short first or last segment within `short_bpm_ratio` of the other side's tempo is the song's own tempo cut short by the edge, so only the other side has to carry the felt section. In return the felt section has to be short enough to count as near the edge (see the edge limits below). The intro then goes into the long segment by the 3b short rule.

Runs of two or more short segments fold in when the segments on either side have the same tempo (within `bpm_shift_ratio`) and the longer side's lines, carried through the run, catch the other side's beats at least `run_fit_min` (0.8) as well as its own lines do. Whole beats lost inside the run don't count, only that the grid comes out on the same lines. 215.48 then 203.41 is madmom dropping a beat: 24 tracked beats over 25 grid beats, after which the 219.93 segment is 2 ms off the grid it left. The run's beats are left out of the fit, with no note.

A felt section at the very start or end folds in on its own (`edge_fold`) when it is under `edge_max_share` (10%) of the song or `edge_max_bars` (8 bars of 4/4 at the neighbour's tempo), whichever is longer, and scores at least `edge_fit_min` (0.9) against its one neighbour. That's stricter than the 0.8 in the middle, since nothing on the other side says the song comes back out of it. A modulation over the last 30% stays split.

What's left is ENDYMION's outro, which the edge rule can't fold. The 292.75 section is a clean 4/3 (a score of 1.00 on the 220 grid's quarters), but it sits between the long 220 segment and the 267.87 one, and that is no ratio of it, so it isn't a felt section by the middle rule. The 267.87 segment has steady 224 ms gaps, 1.5% faster than 6/5, so over its 19 beats it drifts 64 ms off any small subdivision of 220. Its beats land on the 220 grid's subdivisions in 47% of cases, where random times would in 59%. Nothing in the beats says it's on the 220 grid. It's 6% of the song, and with the audio the weak edge rule could still take it if the outro is quiet (`weak_energy_db`), which the beats-only test can't check. "match previous" twice puts it on the 220 grid by hand.

### YOUNITHM

One segment at 259.9956 was right, but 125 of 753 beats were outliers. madmom slides onto the off-beat four times. The residual ramps to half a beat over about 5 beats, stays there and ramps back:

| beats half a beat off (ms) | beats | with the ramps, beats over 15 ms off (ms) |
| --- | --- | --- |
| 48663.6 → 52872.3 | 19 | 47913.6 → 53398.0 |
| 66260.2 → 71986.2 | 26 | 65634.5 → 72374.9 |
| 122322.7 → 125286.4 | 14 | 121712.5 → 125913.7 |
| 146294.0 → 153711.2 | 33 | 145516.7 → 155408.2 |

These may be the parts charted at 130. That needs checking by ear.

An off-beat run is `offbeat_min_beats` (8) or more beats in a row within `offbeat_band` (15% of a period) of half a beat off their segment's grid, with one beat that isn't allowed inside. Two bars, since a tracker that drifts a whole beat passes through the half in fewer. The run's beats are left out of the fit and measured against the half lines. The report lists the runs as `offbeat_runs` (schema 2.2), the timeline hatches them, and the segment panel lists the ones in the selected segment. For YOUNITHM that took the 95th percentile residual from 110.9 to 18.3 ms and the largest from 115.2 to 79.2 ms (a ramp beat), and the confidence from 0.786 to 0.886. The bpm moved from 259.9956 to 259.9963.

When the tracker sits on the off-beat long enough, segmentation splits that stretch off as its own segment at the same tempo, half a beat out of phase. `offbeat_fold` puts it back. A middle segment at both neighbours' tempo whose beats land on their half lines (scored like the ratio check, against `ratio_fit_min`) goes into the longer neighbour, and the off-beat pass then marks it. That only applies between two neighbours: a phase that moves half a beat and stays is a real change (the milestone 3 test with a half beat pause).

The grid's phase comes from the onsets when the audio is there, not from where most tracked beats are. For each segment the pipeline reads the onset strength on the grid's lines and on its half lines. If the half lines' median is `offbeat_phase_ratio` (1.5) times the lines' or more, the grid moves half a beat (keeping its period) and the tracked beats become the off-beat run. The beats-only regression tests can't do this. For YOUNITHM they check that the beats outside the runs sit on the grid (median residual under 5 ms).

### manual bpm

The 60–320 range was already only for detection. `set_bpm` takes up to 1000 bpm, so ×2, the ratio buttons and "set bpm" can set ENDYMION to 440. There are tests for it now, in the api and the frontend.

### thresholds added

| setting | value |
| --- | --- |
| `ratio_subdivisions` | 1, 2, 3, 4, 6 |
| `edge_max_share` | 0.1 |
| `edge_max_bars` | 8 |
| `edge_fit_min` | 0.9 |
| `run_fit_min` | 0.8 |
| `offbeat_band` | 0.15 |
| `offbeat_min_beats` | 8 |
| `offbeat_phase_ratio` | 1.5 |

Each has a test in `tests/test_tempo_map.py` that flips its decision. The 3b results hold: MisoilePunch♪ is still one segment at 270.0038 with its two notes, 300 of 300 random change tracks are right with change points within 0.005 beats, and 0 of 500 steady tracks split. The beats of きゅうくらりん and I Wanna weren't part of this, so they need another eval run.

### limits

- ENDYMION's outro, above.
- The 6/5 merge rests on the tempo ratio as much as on the phase, since madmom's beats in that section are too loose to show a lock to the sixths.
- A short run at a different tempo between two segments on one grid now folds whatever its tempo, as long as it's made of two or more short segments. A real two-bar break at another tempo that comes back exactly on the grid would be folded too.
