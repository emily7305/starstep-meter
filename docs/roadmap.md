# roadmap

The history of the project by version, followed by the manual check to run for each one. The numbers and thresholds behind each step are in `decisions.md`, and each schema change is in `schema-changelog.md`. The README describes the tool as it is now.

## History

### Milestone 1

Upload, decode with ffmpeg, find where the music starts and ends (the trim), and a coarse bpm estimate. The report gets its first shape, which is the schema the later versions grew from. madmom was probed for installing (see `decisions.md`, "madmom install").

### Milestone 2

Beat tracking with madmom, or with a librosa fallback when madmom isn't installed, onset snap of each tracked beat, and a linear fit through the snapped beats for the bpm and the time of the first downbeat. The waveform timeline with the beat grid, a zoomed view, and the first downbeat editable in 1 ms steps. The report records the codec and the decoder padding of the source file.

### Milestone 3

Milestone 3 runs on your own machine, and adds tempo maps to the beat tracking of milestone 2. You upload a song in the browser, and the backend decodes it with ffmpeg, finds where the music starts and ends (the trim), and tracks beats and downbeats with madmom, or with a librosa fallback when madmom isn't installed. A check for half or double tempo runs on the tracked beats, and every tempo path searches 60 to 320 bpm by default. Each tracked beat is snapped onto the nearest onset, and the snapped beats are split into tempo segments. Each segment gets its own bpm and its own anchor, the time of its first downbeat, from a linear fit through its beats, so the first downbeat of the song is `tempo_map[0].anchor_ms`. The beats are written to their own file next to the report. The browser shows a waveform timeline with the segments as bands and the beat grid on them, and a zoomed view for checking the grid against an attack. A segment can be split, merged with a neighbour, given an exact bpm, doubled or halved, and have its anchor moved in 1 ms steps, with every edit recorded in the report's `edits`. A job reopens from the url or from the recent list, and picking a file that was analyzed before offers to reopen it. The report also records the codec and the decoder padding of the source file. A CLI does the same analysis for one file.

### Milestone 3b

Dotted and triplet feel sections (a tempo at a simple ratio of the notated one) are kept on the notated grid as notes on their segment, and the `match` edit joins a segment to its neighbour's grid. The residual tests were changed to cope with beats that sit off the grid for a few beats at a time, which took the first real song, MisoilePunch♪, from 9 segments to one. The health check now imports madmom instead of only finding it, and a failed re-analysis keeps the last good report on screen.

### Milestone 3c

Five real songs went through `scripts/eval_local.py`. The ratios for felt sections are no longer a fixed list, stretches where the tracker followed the off-beat are marked as off-beat runs and left out of the fit, short runs and felt sections next to the start or the end of a song can fold into their neighbour, and tests were added for a bpm set by hand up to 1000.

### Milestone 4

Milestone 4 adds meter and notation suggestions. The analysis infers the meter (beats per bar) of each tempo segment from madmom's downbeats, and the accents get a say where they are clearly stronger than the other beats of a bar. Bar lines are drawn from the meter map, and a meter can be set by hand per region. It also suggests where a chart may write the pulse at half or twice the tempo (a half or double time feel, read from the kick and snare bands), and where a first or last stretch of the song may be its neighbour's tempo (a fold). Suggestions are never applied automatically. Each one can be applied, as one edit (a half or double time feel leaves every grid line where it is), or dismissed, and both stay through re-analysis.

### Milestone 4b

The three real songs were analyzed again with the meter and the band strengths. The accent rule stopped reading the fade-out of MisoilePunch♪ as a 3/4 stretch, and the fold score weighs each segment of an edge stretch by its level and length, which made ENDYMION's outro a fold suggestion. The half and double time detector found nothing on the real songs, because their drums show no plain backbeat in the bands it reads, and it was left as it was (see `decisions.md`, "half and double on these songs").

### Milestone 5

Milestone 5 adds export and a way to check the grid by ear. The timing JSON downloads from the browser, with the beats file if asked for, and is checked against the JSON Schema in `shared/schema/` before it goes out. A Sonolus preset gives the values a Sonolus level needs (the bgm offset in seconds, the bpm changes and the time signatures), with a decoder compensation setting for a player that decodes the audio differently from ffmpeg. A click track plays a click on every beat and an accented one on every bar line, on the same audio clock as the song. Every manual change is one entry in the edit log. Old jobs are deleted after 14 days without a change, one job can be deleted by hand, and a job still waiting in the queue when the server stops runs when it starts again.

### Milestone 6

Milestone 6 adds a second opinion on the beats, a confidence for the tempo map, and a list for setting up a chart. librosa's beat tracker runs as a cross-check next to madmom and flags the tempo segments where the two disagree by more than a configurable number of ms (felt sections and off-beat runs are left out, since the grid deliberately doesn't follow the tracker there). Every tempo segment and every stretch of 16 grid beats gets a confidence from the fit residuals and that agreement, and the low ones are shaded on the timeline. A chart setup panel lists the music offset and every bpm and time signature change by measure, for typing into a chart editor (MikuMikuWorld was the one checked). The zoomed view draws the wav at its own sample rate, and the playhead is drawn behind the sound by the output latency the browser reports. Jobs can be deleted from the recent list.

What broke on the way, and what was changed:

- The first cross-check ran librosa once over the whole song at its own tempo guess. On every tempo change track it was off the beat in the segments at the other tempo, and right segments got a confidence of 0.75. It now runs on each tempo segment on its own, at that segment's bpm, so the comparison is about which attacks the two trackers chose.
- Bar 0 moved. It had been the first downbeat, with any bar before it numbered negative. It is now the first bar line at or after 0 ms of the audio file, so the bar numbers on the timeline run 0, 1, 2 from the left and are the measures of the chart setup list. With a lead-in shorter than a bar it is still the first downbeat. With a longer intro the first downbeat gets a later number.
- Two segments are fitted on their own, so the beat where one hands over to the next is rarely whole. On a 120 to 150 bpm click track it was 0.77 ms off the first segment's line, which made the bar before the change 4.0015 beats and came out as a time signature of 64/64. A bar length or a change within 2 ms of whole beats is now taken as whole.
- The zoomed view drew from wavesurfer's 8 kHz decode, which left 320 samples at 40 ms wide. It now reads the decoded wav itself.
- The playhead is drawn behind the rendered position by the output latency and base latency the browser reports. Only the drawing moves.
- Decoder padding: MikuMikuWorld plays an mp3's decoder padding, so the chart setup list shows an offset for the wav converted with ffmpeg and one for the original file.
- The Sonolus decoder compensation default is still 0 ms. It waits on the test level in the README ("Checking the offset in Sonolus"), and there is no result from the real app yet.

### Milestone 6b

Milestone 6b checked the cross-check and the timing on real songs, fixed one bug, and rewrote the README for someone opening the repository for the first time.

- The three real songs were analyzed again, so their beats files carry librosa's beats and `tests/test_real_song.py` runs the cross-check on them. The segments that are right sit 4 to 7 ms apart (MisoilePunch♪ 7.13 ms, YOUNITHM 4.16 ms, ENDYMION 6.99 ms), and the one flagged is the 267.87 bpm stretch of ENDYMION's outro at 20.75 ms, which the chart has at 220. Click tracks give 0.01 ms. The 20 ms limit stays.
- The start of MisoilePunch♪ looked late in the zoomed view (`tracked 944.068 ms · grid +7.170 ms`), and about −92 ms sounded right with the mp3 against the panel's −85.382 ms. Checked stage by stage, the fit and the anchor are not late. The grid is about 7 ms early on this song, where librosa's beats sit 7.7 ms after it, and on the other two songs the trackers agree. It looks like madmom's bias on this song's attacks, and the onset snap barely moves beats on full mixes, so it can't correct for it. Nothing was changed, because a correction tuned on one song by ear would move every other song. Nudging the anchor by hand is the way to correct it.
- A meter change came out one bar late. On a click track with a 7/4 change at beat 144, the 7/4 started at beat 151, with or without a tempo change before it. The accent runs were at fault: the first 7 beat bar starts on an accented beat and the three beats after it are plain, so it also reads as one more bar of 4/4, and when two accent runs claim the same bar the longer one keeps it. A run whose last bar is where a run of another length starts now gives that bar up first. Both tracks put the 7/4 on beat 144 within 0.7 ms.
- The two offsets in the chart setup list differ by exactly the decoder padding. Both were already worked out from unrounded values, and the panel now says so, with a test that checks the difference to 1e-9 ms.
- The `for your chart` card above the timeline gives the plain answer right after an analysis: the bpm, the offsets and the time signature, each with a `?` explanation, a line when they change, and a warning when a stretch came out with low confidence. Its numbers come from the chart setup list.
- The README was rewritten around what the tool does, its status, the install, a workflow from upload to an editor, and the exports. The history and the manual checks moved to this file.

### Milestone 6c

Milestone 6c moved where the chart starts. Measure 0 had been the first bar line in the audio, which on a song with a long silent start (SHIKI - Lapis, about 8 s at 145.99 bpm) left four or five empty measures before the music and an offset that didn't skip the silence. Now the music starts at the trim start, or at the first tracked beat when that is earlier. The bar it starts in is measure 1, and measure 0 is one empty bar before it, so the offset is minus where measure 0 starts and is positive when the silence is shorter than a bar. The setting `music starts at measure` in the chart setup panel can put the music at measure 0 instead, and is remembered per browser. The timeline, the chart setup list and the `for your chart` card use the same numbering, and bars before measure 0 are drawn faintly with no number. The Sonolus export keeps its own beat 0. MisoilePunch♪ moved by one bar, from offsets of `-62.362` and `-85.382` ms to `826.515` and `803.494` ms. The reasons are in `docs/decisions.md` (where the chart starts).

### Milestone 7

Milestone 7 is about using the tool. The timeline can be driven with the mouse: a drag held near either edge keeps scrolling, faster the closer it is, the wheel scrolls sideways and Ctrl with the wheel zooms around the mouse, and a thin overview strip shows the whole song with the visible part outlined. Both views are labelled, the big one `whole song` and the small one `zoomed view around the playhead` with its width. Before a song is open the page is one large drop area with a `choose a song` button, and a song can be dropped anywhere on the page. The layout uses the whole width at 1920 and 1366 pixels, nothing is smaller than 12 px, sentences are 14 px, and small secondary text moved to a darker colour that passes 4.5:1. A first-visit tour of five steps can be opened again from `?` in the header, every control has a tooltip, and a footer says who made it and under which license.

Analysis changes:

- SHIKI - Lapis had an odd bar at measure 38 and its first downbeat a beat late. The octave check's doubled beats were counted per tracked beat, so one extra beat in a quiet bar moved every downbeat after it, and madmom took the song's first beat for a pickup. Bar positions the octave check counts are now counted on the grid, and the first beat is beat 1 unless the tracker's pickup holds up in the accents. Lapis is 4/4 all the way through with measure 1 on its first beat.
- Swing and gallop sections are found from where the onsets sit between the grid lines, with the note division a chart editor needs there, as suggestions in the list and a line in the chart setup panel (schema 2.5).
- Re-analysis moves the job to the top of the recent list with the time it finished, and a test checks that it runs every stage again and replaces every auto result.
- The Sonolus export is removed. The timing JSON is the one export.
- `scripts/measure_bias_local.py` measures madmom's raw beats against the strongest nearby onsets on a folder of songs, for checking the 11.8 ms bias on real music.

## Manual checks

These are the checks that were written down for each version, in order. The expected values are for madmom unless it says otherwise. Start the backend and the frontend as described in "Running" in the [README](../README.md#running).

Two things changed in the UI after most of these were written. Bar numbers on the timeline start at 0 on the first bar line in the audio, not on the first downbeat. That is the same line for the click tracks below whose lead-in is shorter than one bar. The milestone 1 track has a 2 s lead-in, which is a full bar at 120 bpm, so there bar 0 can be earlier than the first downbeat. And the `for your chart` card now sits above the timeline with the bpm and the offsets, so a check that reads a number from the report column can also read it there.

Milestone 7 removed the Sonolus export. The steps below that use the `sonolus` preset, its decoder compensation or `scripts/make_sonolus_test_level.py` no longer apply, and the export block has only `include beats.json` and `export json`.

A third change came with milestone 6c. The bar the music starts in is now measure 1 and measure 0 is one empty bar before it. For the tracks below, whose music starts in the first bar, every measure or bar number read from the timeline or the chart setup list is one higher than the checks say, and the offsets are minus where measure 0 starts, which is positive when the silence before the music is shorter than a bar.

### Milestone 1 manual check

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

### Milestone 2 listening check

Since milestone 3 the offset below is the first segment's anchor (`tempo_map[0].anchor_ms`, which replaced `beat_offset_ms`), so its steps are the `−1 ms` and `+1 ms` buttons under the segment controls, and the edits list names the field `tempo_map/0/anchor_ms`. The anchor is also the `first downbeat` row of the report column. The first downbeat of this track is bar 0 on the timeline, because the lead-in is shorter than a bar. Since milestone 6c it is measure 1.

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

Expected: `beat_offset_ms` about 136.77, and bpm 120.0 with confidence 1.0. Onset snap lands about 0.7 ms before a click's first sample on these clicks (see `decisions.md`), which is why the offset is a little under 137.506. The test tolerance is 5 ms. With `-v`, the snap line shows a median move of about +7 ms, which is madmom's early bias being removed. (The report no longer has a `beat_offset_ms` field, the same number is the anchor of the first segment. On the mp3 of this track a current checkout gives 136.780 ms.)

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

The decoder padding row shows 1105 samples (25.057 ms), and the beat offset stays about 136.8 ms, because ffmpeg honours the LAME gapless header. A player that ignores that header would play this MP3 about 25 ms late. That correction was left for export later and is not part of the anchor. It is now in the chart setup list (the second offset) and in the decoder compensation of the Sonolus export, see the milestone 5 and 6 checks.

For the Japanese title check, copy the WAV to a Japanese name and upload it:

```bash
cp click-137.wav "テスト曲 120.wav"
```

The name should show in the rounded face (M PLUS Rounded 1c) in the timeline, the picker and the report, not in a system font.

Last, try a real song. Play from a few bars in and watch whether the bar lines land on the kick or snare you hear. If they drift across the song, it isn't one steady tempo. Since milestone 3 that shows up as more than one tempo segment, see the milestone 3 check below.

Don't commit the generated audio.

### Milestone 3 listening check

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

Then the UI check. Start the backend and the frontend as described in Running, upload `tempo-check.wav`, and wait for the job to finish. The timeline should show two bands, labelled 150.00 bpm and 200.00 bpm, and the tempo map list in the report should show the same two segments, both auto. The `for your chart` card reads `bpm at the start` with 150.00 and says the song changes speed once.

1. Click into the second band. It gets the pink accent, and the controls on the right now show segment 2 of 2.
2. Press ×2. The band's label reads 400.00 bpm · manual, and the edits list shows `tempo_map/1/bpm` as 200 bpm → 400 bpm (the fitted value can differ from 200 in the fourth decimal), plus a `source` entry (auto → manual) and a `confidence` entry that ends at –. Since milestone 5 this is one entry, `tempo_map/1`, with a line each for `bpm`, `confidence` and `source`.
3. Press ÷2 to go back. The label reads 200.00 bpm · manual again, and the edits list gets one more `tempo_map/1/bpm` entry, 400 bpm → 200 bpm.
4. Click the second band again so the timeline has focus, then press → three times. The anchor reads 3 ms later. After about half a second "saved" appears, and the edits list gets one `tempo_map/1/anchor_ms` entry for the 3 ms.
5. Reload the page. The url holds `?job=...`, so the same job comes back, with the same bands and the same edits.
6. Pick `tempo-check.wav` again and press analyze. It says the file was analyzed before and offers "reopen" and "analyze again as a new job". Press "reopen".
7. Press "re-analyze". The second band stays as it was, 200.00 bpm · manual with the moved anchor, and the edits list is unchanged, because re-analysis isn't an edit. The first band is fitted again from the same audio.

Next the fast-song check:

```bash
python scripts/make_click_track.py fast-270.wav --bpm 270 --beats 160 --lead 0.4375 --accent
```

It should come out at 270.00 bpm, not 135. If a real fast song comes out at half its tempo, ×2 on its segment fixes it. The cases that are still ambiguous are off-beat eighth notes at 50 to 80% of the weaker beats' level, fast songs where every other beat is much quieter, and a switch to exactly half or double tempo on a steady beat (see "tempo range and half or double" in `decisions.md`).

Don't commit the generated audio.

### Milestone 3b check

A 270 bpm track with eight bars of a dotted 3-3-2 rhythm in the middle. The chart tempo stays 270, so the map should too:

```bash
python scripts/make_click_track.py dotted-check.wav --bpm 270 --beats 288 --lead 0.6113 --accent --rhythm 128:32:0,1.5,3
python -m backend.analysis.cli dotted-check.wav -v
```

`--rhythm 128:32:0,1.5,3` means 32 beats from click 128 where the clicks play 0, 1.5 and 3 beats into each 4 beat bar. With madmom the CLI prints one segment at 270.0000 bpm and a `kept ... on this grid` line under it, at about 29388 to 35944 ms, 203.36 bpm on its own (3/4). In the UI the segment panel lists the section under "kept on this grid". "split out" gives three segments, 270.00, 203.36 and 270.00, and "match previous" on the middle one puts it back on the 270 grid as one edit. Since milestone 5 "split out" is one edit too, logged as the tempo map before and after.

For comparison, a real change of tempo at the same ratio that doesn't come back stays as two segments, 270.00 and 202.50:

```bash
python scripts/make_click_track.py modulation-check.wav --bpm 270 --beats 224 --lead 0.6113 --accent --change 128:202.5
```

Don't commit the generated audio.

### Milestone 3c check

A 260 bpm track where only the off-beats click for 32 beats:

```bash
python scripts/make_click_track.py offbeat-check.wav --bpm 260 --beats 288 --lead 0.5531 --accent --rhythm 128:32:0.5,1.5,2.5,3.5
python -m backend.analysis.cli offbeat-check.wav -v
```

With madmom the CLI prints one segment at 260.0000 bpm with its anchor on the first click (about 552.4 ms), and an `off-beat` line under it at about 30437 to 36899 ms. madmom follows the off-beat clicks there and takes a beat or two to go over and to come back. In the UI that stretch is hatched on the timeline and listed under "off-beat runs" in the segment panel. Since milestone 6 the same stretch is not shaded as low confidence, because the grid is on the real beats there.

Don't commit the generated audio.

### Milestone 4 check

The expected values below are for madmom.

First a meter change, a 140 bpm track that is 4/4 and then has 7 beats to the bar:

```bash
python scripts/make_click_track.py meter-check.wav --bpm 140 --beats 148 --lead 0.52 --accent --meter 64:7
python -m backend.analysis.cli meter-check.wav -v
```

`--meter 64:7` means click 64, counted from 0, is a downbeat and the bars from it on have 7 beats. The script prints the change at click 64, at 27948.571 ms.

The CLI prints one tempo segment at 140.0000 bpm with its anchor at 519.274 ms, then `meter   2 segment(s)` with `[0] 519.546 -> 27947.849 ms, 4/4` and `[1] 27947.849 -> 63550.363 ms, 7/4`, both with confidence 1.00. Seven beats of the grid come out as 7/4. Whether the chart writes that as 7/8 at twice the bpm is a notation choice the audio can't make, so set it in the meter panel if it does. (Since milestone 6 the CLI also prints a `check` line and a `conf` line after these.)

Then the UI check. Start the backend and the frontend as described in Running, upload `meter-check.wav`, and wait for the job to finish.

1. The meter panel under the zoomed view reads "meter 1 of 2" and 4/4. Click the waveform past 28 s and it reads "meter 2 of 2" and 7/4.
2. The bar lines on the timeline are every 4 clicks, and every 7 after the change. The `chart setup` panel lists the change as a `7/4` row at `m.16`, where the 7 beat bars start. Since milestone 6c that row is at `m.17`, one higher.
3. With "meter 2 of 2" in the panel, set 3/4 with "set meter". The edits list shows `meter_map/1/numerator` (7 → 3), plus `meter_map/1/confidence` and `meter_map/1/source` (auto → manual). "split meter here" on a beat in the zoomed view logs the whole `meter_map` before and after instead. Since milestone 5 the first of these is one entry, `meter_map/1`, with a line for each of the three values.
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
3. Press "apply" on the half time one. The tempo map becomes 130.00, 65.00 and 130.00 bpm, with the middle one manual and the bars in it twice as long. The edits list gets a `tempo_map` entry and a `notation_suggestions/0/status` entry. Since milestone 5 that is one entry, labelled `tempo_map + notation_suggestions/0/status`.
4. Press "dismiss" on the other one. The edits list logs its status.
5. Press "re-analyze". Neither suggestion comes back.

The suggestions are tuned on these synthetic drums only, so run `scripts/eval_local.py` on your songs again and compare the `notation_suggestions` column with the charts. To let `tests/test_real_song.py` check MisoilePunch♪ (4/4 and no suggestions), YOUNITHM (half at the measures charted at 130, an expected failure for now) and ENDYMION (a fold for its outro), analyze each one again and copy its `beats.json` and `report.json` into `tests/real/<song>/` as before. The same folders now also feed the confidence and cross-check tests, which use `cross_check_beats` from the beats file when it has them.

Don't commit the generated audio.

### Milestone 5 listening check

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
5. Pick "sonolus" and the 25.057 ms preset (its button reads `25.057 ms, 1105 padding samples`) and export. `bgmOffset` is −1.838163 and `first_downbeat_beat` 4, the same as before the split, and `bpm_changes` has 120 bpm at beat 0 and 240 bpm at the beat of the split.
6. Re-analyze. The manual segments stay, the click track follows them, and the edits list is unchanged.

Then a real song. Play it with the click track on from a few bars in. If the accents drift off the downbeats, the tempo map is off there, and the timeline shows where.

Don't commit the generated audio.

The check of the Sonolus preset in the real app made two test levels with `scripts/make_sonolus_test_level.py` from the exports of step 5. It never got a result, and the preset was removed in milestone 7.

### Milestone 6 check

The chart setup list and the `for your chart` card, on the mp3 of the accented click track from the milestone 2 check (`click-137.mp3`, made as in the milestone 5 check). Upload it and wait for the job to finish.

Expected with madmom: the first downbeat is at 136.780 ms and the decoder padding is 1105 samples at 44.1 kHz, 25.057 ms. Measure 0 is the first downbeat, because the lead-in is shorter than a bar. So the offset is about `-136.780` ms with the wav from ffmpeg and about `-161.837` ms with the original mp3, and the two differ by the padding. These come from the analysis of the same file on the command line and the formulas in `frontend/src/chartSetup.ts`, they were not read off the page.

Since milestone 6c the first downbeat is measure 1 and measure 0 is one bar of 2000 ms before it, so the offsets are about `1863.220` ms with the wav and about `1838.163` ms with the original mp3, worked out from the same numbers. The `m.` rows below are still at `m.0`.

1. The `for your chart` card above the timeline reads 120.00 for the bpm, both offsets and 4/4, with no line about changes and no warning.
2. In the `chart setup` panel, the `music offset` item shows the same two offsets. `audio file` shows `ffmpeg -i "click-137.mp3" "click-137.wav"`, and `copy command` copies it. The list has two rows, `m.0 · 4/4` and `m.0 · 120.00 bpm`.
3. Run the command, load `click-137.wav` in MikuMikuWorld, type the first offset into the music offset field, and listen whether the editor's first measure and beats land on the clicks of the song. With the original mp3 and the second offset it should sound the same.
4. Under the play time, a line like `playhead −42.0 ms output latency` shows the latency the browser reports. Press `click track` and play. Check the playhead against a click on wired output.
5. Zoom the zoomed view to 40 ms. The attack is drawn from the wav at its own sample rate, 44.1 kHz here.
6. Press `delete` on this job in the `recent` list. It asks `delete this job and its files?`. Press `cancel`, and nothing changes. Press `delete` and then `delete` again, and the job is gone from the list and its folder from `data/jobs/`.
7. On a track with a change, like the milestone 3 one, the chart setup list has a row for the change (`m.16 · 200.00 bpm`, click 64 being the start of bar 16; since milestone 6c it is `m.17`, one higher) with a matching label on the timeline, and the cross-check text in the segment panel reads about `librosa 0.01 ms apart` for each segment.

### Milestone 6b check

The meter change that came out one bar late. A click track at 120 bpm that changes to 150 bpm at click 96 and has 7 beats to the bar from click 144:

```bash
python scripts/make_click_track.py late-check.wav --bpm 120 --beats 192 --lead 0.5 --accent --change 96:150 --meter 144:7
python -m backend.analysis.cli late-check.wav -v
```

The script prints the tempo change at 48500.000 ms and the meter change at 67700.000 ms. Expected with madmom: two tempo segments, 120.0000 bpm and 150.0000 bpm, and `meter   2 segment(s)` with `[0] ... 4/4` ending at 67699.264 ms and `[1] 67699.264 -> ... 7/4`, which is click 144 within the 0.7 ms of the onset snap. Before the fix the 7/4 started at click 151. In the UI the chart setup list shows the 7/4 at `m.36`, 24 bars at 120 bpm and then 12 at 150. Since milestone 6c it shows `m.37`, one higher.

Then the plain answer. On `late-check.wav` the `for your chart` card reads `bpm at the start` with 120.00, and a line `this song changes speed once and changes time signature once.` with a `see every change` link that jumps to the chart setup list. Press `more decimals` and the bpm shows 4 decimals. Press `copy` and paste somewhere: the text has the same lines as the card.

Finally the offsets. For a real mp3 with decoder padding, the two offsets differ by the padding to the last digit worked out before rounding. MisoilePunch♪ is the example: `-62.362` ms with the wav and `-85.382` ms with the mp3, with 23.021 ms of padding. A 0.001 ms difference from subtracting the rounded numbers is expected.

Don't commit the generated audio.

### Milestone 6c check

Where the chart starts. A click track with 8 s of silence before the first click, at 145.99 bpm:

```bash
python scripts/make_click_track.py silent8.wav --bpm 145.99 --beats 96 --lead 8 --accent
```

The script prints the ground truth. The first click is a downbeat at about 8000 ms, and one bar is 1643.948 ms. Upload `silent8.wav` and wait for the job to finish. The values below depend on the analysis, so they are about values, worked out from `docs/decisions.md` (where the chart starts), where the first downbeat came out at 7999.268 ms.

1. On the timeline the bars over the silence are drawn faintly and have no number, and the bar lines before 0 ms of the file are not drawn. A bar line at about 6355 ms is numbered 0, the bar line on the first click is numbered 1.
2. The `for your chart` card and the `music offset` item in the `chart setup` panel read about `-6355` ms (`-6355.320` ms in the example above) for the wav. A wav has no decoder padding, so both offsets are the same. `music starts at measure` has `1` pressed, and the note under the offsets says the music starts in measure 1, at about 7999 ms, and that measure 0 starts about 6355 ms into the audio file.
3. Press `0` next to `music starts at measure`. The offset becomes about `-8000` ms (`-7999.268` ms in the example), the first click is numbered 0 on the timeline, the bars before it are faint with no number, and the note no longer mentions a lead-in bar.
4. Reload the page and open the job again from the `recent` list. `0` is still pressed, and the offset is still about `-8000` ms. Press `1` to go back to the default, which is then also remembered.

Don't commit the generated audio.

### Milestone 7 check

Start the backend and the frontend as described in Running.

1. Open the page in a fresh browser profile or a private window. A tour starts: `1 / 5`, `load a song`, pointing at the drop area. Press `next` through the five steps and `done`. Reload: it doesn't come back. Press `?` in the header: it starts again at step 1.
2. Before any song is open the page is the drop area, `drop a song anywhere on the page`, with `recent` beside it, and nothing else large and empty at 1920×1080 or 1366×768. Drag an audio file over the page: it says `drop the song to load it`. Drop it: the file name and `analyze` show in the drop area. Drop a text file: a line says it's not an audio file.
3. Analyze a song of a few minutes. The `for your chart` card is at the top with both offsets side by side, and the timeline under it is labelled `whole song`, with the overview strip above it.
4. Hold Ctrl and turn the wheel over the timeline: it zooms around the mouse, and the readout between `−` and `+` shows the px/s. Zoom to about 100 px/s. The wheel now scrolls the timeline sideways, Shift with the wheel too.
5. Press on the waveform, drag to the right edge and hold still there: the timeline keeps scrolling right, faster when the pointer is right at the edge or past it, and the playhead moves along. Drag back into the middle: it stops. Do the same at the left edge.
6. Click in the overview strip near its end: the timeline jumps there, and the outlined part moves with it.
7. The zoomed view is labelled `zoomed view around the playhead ±60 ms`, and `40 ms` and `400 ms` change that to `±20 ms` and `±200 ms`.
8. Hover over buttons: each has a tooltip. Nothing on the page is smaller than 12 px.
9. Press `re-analyze`. When it finishes, the job is at the top of `recent` and says `re-analyzed at` with the time.
10. Swing and gallop, on a click track with softer ticks between the beats:

    ```bash
    python scripts/make_click_track.py swing-check.wav --bpm 146 --beats 128 --lead 1 --accent --subdivision 32:32:2/3 --subdivision 64:32:1/2,3/4
    ```

    The script prints the swing from about 14150.7 to 27301.4 ms and the gallop from about 27301.4 to 40452.1 ms. Analyze it. The suggestions list has a `swing 2.00:1` row with `1/12` and a `gallop, 8th-16th-16th` row with `1/16`, each starting within a bar of those times, and the chart setup panel has a line for each, like `m.9 to m.16 · swing 2.00:1 · 1/12`. Press `÷2` on the segment: the swing row reads `1/24` and the gallop `1/32`.
11. Lapis: analyze `SHIKI - Lapis.mp3`. The meter is 4/4 all the way through, with no `m.38 · 1/4` row in the chart setup list. The offset with the mp3 is about `-7279.6` ms at 291.99 bpm. Press `÷2`: about `-6457.6` ms, with measure 1 on the first beat, 17 ms from the chart's -6475 ms by ear.

Don't commit the generated audio.
