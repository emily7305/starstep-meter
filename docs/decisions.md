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
- The DBN's tempo range is 55–240 bpm. madmom's default upper limit is 215, which would halve the faster rhythm game songs. 230 bpm clicks track correctly with the higher limit.
- Downbeats need something to find. On clicks where every beat sounds the same, madmom picks an arbitrary beat as beat 1, which is correct behaviour. The accuracy tests use accented downbeats, and `make_click_track.py --accent` makes them for the manual check.
- If madmom isn't installed, or is installed but fails to import (the PyPI 0.16.1 build does that), `auto` falls back to librosa. Asking for `--tracker madmom` by name turns either case into an error instead.
- The librosa fallback is `librosa.beat.beat_track` on the milestone 1 onset envelope with the milestone 1 bpm. It has no downbeats, so the first beat is taken as beat 1 of a 4/4 bar, and bar positions are counted on the fitted grid so a dropped beat doesn't slip the bar. The beats file says `tracker: "librosa"` and the confidence is halved.

Raw tracker error against the click onsets, before snapping: madmom −6.4 to −17.6 ms (mean about −11), librosa +4.3 to +12.3 ms. madmom's beats are 10 ms quantized and come in about one frame early, which matches what milestone 1 saw.

Speed: madmom takes about 3 s for 20 s of audio on this cloud VM (4 cores). A 4 minute click track runs the whole CLI in 36 s, and nearly all of that is the network.

## onset snap (milestone 2)

For each tracked beat, compute a spectral flux only around that beat and move the beat to the nearest strong flux peak within ±20 ms. If there isn't one, keep the raw beat. The window is `--snap-window-ms` on the CLI and `STARSTEP_SNAP_WINDOW_MS` for the server.

- The FFT window is 256 samples at 44.1 kHz (5.8 ms), scaled with the sample rate, and the hop is 1/8 of it (0.73 ms) with parabolic interpolation on the peak. Computing it locally keeps it cheap. A 0.7 ms hop over a whole 4 minute song would be about 170 MB of spectrogram.
- The flux is on linear magnitude, credited to the later of the two frames it compares. I measured the variants on jittered beats over wav, mp3 and aac at both sample rates. The mean bias was −0.46 ms with a 4 ms window, −0.77 ms with 5.8 ms and −1.66 ms with 11.6 ms. Adding log compression (`log1p(γ·|X|)`) made each one 0.6 to 2 ms earlier. The spread was under 0.2 ms in every case. 5.8 ms is a compromise. Shorter sits closer to the attack, but on real mixes I'd expect it to get noisy. Revisit with real songs.
- Strong means at least half of the biggest peak in that beat's window, and nearest means nearest to the raw beat. A window whose biggest peak is under 20% of the median over all beats counts as having no onset, which covers a beat in a quiet passage or in silence. Both thresholds are tuned on clicks only.
- The bias is not corrected. On sharp attacks it's a steady −0.73 ms, but it depends on how fast the attack rises, so a constant correction tuned on clicks would be wrong for everything else.

Snapped beats land −0.71 to −0.77 ms from the click onsets, for both trackers, all codecs and both sample rates. So snapping removes madmom's one-frame lead and librosa's late bias alike.

One thing to watch: madmom's worst raw beat was 17.6 ms early, which is only 2.4 ms inside the 20 ms window. If real songs push it further, the snap would miss the attack or catch an earlier one. Centering the window on the raw beat plus one frame would buy margin, but I want to see real songs first.

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
