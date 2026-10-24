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

This is a coarse estimate. Milestone 2 replaces it with a linear regression over tracked beats, and that's where the two-decimal BPM target actually gets tested. It only runs on the trimmed region.

1. Onset strength envelope with `librosa.onset.onset_strength`, hop of 256 samples at 44.1 kHz (5.8 ms per frame). The hop is scaled with the sample rate (279 at 48 kHz) so frames are the same length in ms.
2. `librosa.feature.tempo` for a first guess. It's in `librosa.feature` in 0.10+, and the old `librosa.beat.tempo` alias is deprecated.
3. Octave check. Take the guess, half of it and double of it, keep the ones in 60–240 BPM, and look up the autocorrelation of the onset envelope at each one's beat period. A click on every beat also lines up at 2 and 4 beats, so slower octaves always look supported. The fastest candidate whose peak is at least half the strongest peak wins.
4. Refinement. librosa's tempo bins are whole frame lags, about 1.4 BPM apart at 120 BPM and 2.9 BPM apart at 174 with this hop, which alone can miss ±1 BPM. So the code finds the autocorrelation peak at 1, 2, 3, ... up to 32 beat periods (or half the envelope), interpolates each one parabolically, and fits lag = k × period through all of them. The autocorrelation is divided by its overlap count first, so long lags aren't biased short. If the refinement moves more than 3% away from the octave pick, it falls back to the pick.

Measured on synthetic click tracks (40 beats, 15 tempos from 60 to 233.3 BPM, 44.1 and 48 kHz, plain, -90 dBFS noise, and accented downbeats): the worst error is 0.017 BPM and there are no octave errors. librosa's raw estimate on the same tracks reported half tempo for 174 BPM and up at 44.1 kHz, and for 160 and 180 and up at 48 kHz. It was up to 0.99 BPM off on the rest. So the octave check and refinement are doing real work.

Known limits: click tracks are the easy case. Real music with strong eighth notes will push the octave check towards double time, and swing or tempo drift isn't handled at all. 60–240 is a guess at a sane range for charts, and songs above 240 will come out at half tempo. `confidence` stays null until there's something meaningful to put there.
