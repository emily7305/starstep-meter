# schema changelog

Any breaking change to the timing report bumps `schema_version` and gets an entry here. The JSON Schema in `shared/schema/timing_report.schema.json` is generated from `backend/schema/models.py` with `python -m backend.schema.export_schema`; a test fails if the committed file is stale.

## 1.0

First version, written in milestone 1 so the shape doesn't churn later.

Top level: `schema_version`, `source` (filename, sha256, duration_ms, sample_rate), `trim` (start_ms, end_ms), `beat_offset_ms`, `tempo_map`, `meter_map`, `sections`, `edits`.

Milestone 1 fills `source`, `trim`, and one `tempo_map` segment at `trim.start_ms` with `source: "auto"` and `confidence: null`. `beat_offset_ms` is null and the other lists are empty.

Conventions this version commits to:

- All times are milliseconds from the first sample of the decoded audio, before trimming.
- `sha256` is the hash of the original upload, not of the decoded WAV.
- Bars are 0-based. `beat_in_bar` is 1-based, so beat 1 is the downbeat.
- Meter denominators must be powers of two.
- Every segment carries `source: "auto" | "manual"`. Re-analysis replaces only auto segments.
- `edits` is append-only, one entry per manual change, with an ISO 8601 timestamp that includes a timezone.
- Unknown fields are rejected (`additionalProperties: false`), so a typo in a hand-edited report fails validation instead of being dropped.
- Beats are stored in a separate file (`BeatsFile` in the same module), not inside the report. Nothing writes it until milestone 2, and its JSON Schema isn't exported yet.

## 1.1

Milestone 2. Additive: new fields only, nothing renamed or removed.

- `source.codec`: codec name of the first audio stream as ffprobe reports it.
- `source.decoder_padding_samples`: samples a decoder that ignores gapless info plays before ffmpeg's first sample, 0 when that doesn't apply. How it's read and the measured values are in `docs/decisions.md` (beat offset convention).
- `BeatsFile`: its JSON Schema is exported as `shared/schema/beats.schema.json` with the TypeScript type in `frontend/src/types/beats.ts`. It gains `tracker` (`madmom` or `librosa`), and each beat gains `raw_time_ms` (tracker output before onset snap) and `residual_ms` (snapped time minus the fitted grid).

Both fields are required, so a 1.0 report doesn't validate as 1.1. Job folders from milestone 1 answer `GET /api/jobs/{id}/report` with a 409 that says to upload the file again. There's no migration, because the codec and padding can only come from the original file.

## 2.0

Milestone 3, tempo maps. Breaking.

- `beat_offset_ms` is gone from the top level. Each tempo segment carries its own phase as `anchor_ms`, a downbeat on that segment's grid (the grid is `anchor_ms + k * 60000 / bpm`), so the first downbeat of the song is now `tempo_map[0].anchor_ms`. A manual segment has to hold its whole grid by itself, otherwise re-analysis couldn't leave it untouched. The reasoning is in `docs/decisions.md` (tempo map).
- Each tempo segment gains `end_ms`. Segments have to be contiguous, every `start_ms` equal to the previous `end_ms`, and `end_ms` has to be after `start_ms`. `tempo_map` can't be empty.
- `confidence` is null when a segment's bpm or anchor was set by hand. A segment that still has a confidence was fitted, by the analysis or by a refit after a split or merge.
- `BeatsFile` gains `octave` (`kept`, `doubled`, `halved` or `mixed`), what the octave check did to the tracker's tempo. `raw_time_ms` of a beat the octave check inserted is halfway between two tracker beats, and `residual_ms` is against the beat's own tempo segment.
- Edits for tempo changes use paths like `tempo_map/2/bpm`. Split and merge log the whole `tempo_map` before and after.

1.1 reports and beats files are upgraded when they're read: `beat_offset_ms` becomes the first segment's `anchor_ms`, the segment ends at `trim.end_ms`, and the beats file gets `octave: "kept"`. The edit log is kept as it was, so old entries still say `beat_offset_ms`. They describe what is now `tempo_map/0/anchor_ms`. The upgraded report is written back as 2.0 the next time it's edited. 1.0 reports still answer with a 409.

## 2.1

Milestone 3b, felt tempo sections. Additive, but a 2.0 reader rejects the new field since unknown fields aren't allowed, so the version moves.

- Each tempo segment gains `ratio_merged`, a list of sections the analysis kept on the segment's grid although they fitted another tempo on their own: a dotted or triplet feel at 1/2, 2/3, 3/4, 4/3, 3/2 or 2 of the segment's bpm. Each has `start_ms`, `end_ms` (inside the segment), `bpm` (what it fitted to on its own), `ratio` (its bpm over the segment's, as a string like `3/4`) and `fit` (how well the segment's grid catches its beats against its own grid). Splitting at a section's `start_ms` and `end_ms` gives it back as its own segment. How the sections are found is in `docs/decisions.md` (tempo map on a real song).
- A new tempo edit, `match`, joins a segment to its previous or next neighbour with the neighbour's grid. It's logged like split and merge, as the whole `tempo_map` before and after.
- `BeatsFile` has no new fields. Its `schema_version` moves to 2.1 with the report's.

2.0 reports and beats files are upgraded when they're read by changing the version only, every segment gets an empty `ratio_merged`. 1.1 files go through 2.0 first, as before.

## 2.2

Milestone 3c, off-beat runs. Additive, but 2.1 readers reject the new field, so the version moves.

- The report gains `offbeat_runs`, a list of `{start_ms, end_ms, beats}`: stretches where the analysis found the tracked beats half a beat off the tempo map's grid, the tracker following the off-beat. The grid stays on the real beats there. It's analysis output, edits don't change it and a re-analysis replaces it.
- A beat's `residual_ms` in the beats file is measured against the subdivision it sits on when it's in a ratio merged section or an off-beat run (half a beat for the latter). For a ratio merged section that was already so in 2.1, the description says it now.
- `BeatsFile` has no new fields, its `schema_version` moves with the report's.

2.1 reports and beats files are upgraded when they're read by changing the version only, with an empty `offbeat_runs`. Older ones go through the earlier steps first.

## 2.3

Milestone 4, meter and notation suggestions. Additive for everything that was ever written, but the version moves, since 2.2 readers reject the new fields and the meter segment changes shape.

- A meter segment goes by time: `start_ms`, `end_ms` (contiguous over the tempo map's extent, like tempo segments), `numerator` (1 to 32), `denominator` (a power of two up to 64), `confidence` and `source`. `start_bar` is gone, a bar number moves whenever a span's bpm is halved or a segment is split. A bar is `numerator × 4 / denominator` beats of the tempo segment's grid. A meter segment that starts with a tempo segment counts bars from its anchor, one that starts inside it starts a bar there. The analysis writes the meter map with source `auto`, an empty one still means 4/4 from every anchor. Why and how bar lines are drawn is in `docs/decisions.md` (meter and notation).
- The report gains `notation_suggestions`, each with `start_ms`, `end_ms`, `kind` (`half`, `double` or `fold`), `suggested_bpm`, `grid_bpm` (the bpm of the segment it was made on), `score` (0 to 1) and `status` (`open`, `applied` or `dismissed`). The analysis never applies one. An edit applies or dismisses it, and a re-analysis keeps the decided ones.
- New edits: `meter_map/<i>/<field>` for a meter set by hand, `meter_map` before and after for a meter split or merge, and `notation_suggestions/<i>/status` for apply and dismiss (apply also logs `tempo_map` before and after).
- `BeatsFile` gains `grid_features`, the band onset strengths (`low`, `mid`, `high`) at every grid line and half line of the analysis' tempo map, plus the lines the fold check carried into an edge stretch. Timing and band numbers only, never audio. The suggestions can be worked out again from them without the audio.

2.2 reports and beats files are upgraded when they're read by changing the version only, with an empty meter map, no suggestions and no grid features. Nothing wrote a meter segment before 2.3, so a 2.2 `meter_map` is empty. One written by hand with `start_bar` has no time to go by and is left as it was, so it fails validation instead of landing somewhere it wasn't meant to. Older files go through the earlier steps first.

## 2.3, milestone 5 (no version change)

Nothing in the timing report or the beats file changed shape, so `schema_version` stays 2.3.

- The edit log has one entry per manual change. `field` is the deepest path that holds everything the change touched. With one changed value, `old` and `new` are that value, as before. With several, they're objects keyed by each value's path under `field`, and an empty `field` is the report itself. So the first edit of an auto segment is one `tempo_map/<i>` entry holding the value, `confidence` and `source`, and applying a suggestion is one entry at `""` holding `tempo_map` and `notation_suggestions/<i>/status`. Entries written before keep the old one-per-field form, the log is append-only. Why there's no bump is in `docs/decisions.md` (edit log, one entry per change).
- A new tempo edit, `split_out`, splits at both ends of a ratio merged section as one edit and is logged like a split.
- Two new schemas for the exports, generated from `backend/schema/export_models.py` like the others: `shared/schema/timing_export.schema.json` (`kind: "timing"`, `exported_at`, the `report`, and the `beats` file only when it's asked for) and `shared/schema/sonolus_export.schema.json` (`kind: "sonolus"`, the level data with `bgmOffset` and the `#BPM_CHANGE` entities, the bpm changes with their times, the time signatures and the decoder compensation that went into `bgmOffset`). The frontend gets `src/types/timingExport.ts` and `src/types/sonolusExport.ts` from them.

## 2.4

Milestone 6, confidence and the cross-check. Additive, but 2.3 readers reject the new fields, so the version moves.

- The report gains `confidence_spans`, a list of `{start_ms, end_ms, confidence, residual_share, agreement, low}` over the auto tempo segments, 16 grid beats each from the segment's anchor (four bars of 4/4). `confidence` is the residual share times the cross-check agreement as in `docs/decisions.md` (confidence, milestone 6), `low` says it's under the threshold the timeline shades at. Analysis output, edits don't change it and a re-analysis replaces it. A span under a manual segment isn't written.
- The report gains `cross_check`, `{tracker: "librosa", max_disagreement_ms, segments}` with one `{start_ms, end_ms, disagreement_ms, compared, flagged}` per tempo segment the analysis found, or null when it didn't run (the main tracker was librosa itself). Analysis output like the spans.
- A tempo segment's `confidence` is worked out with the same formula over the whole segment, halved for the librosa fallback as before. A refit after a split or merge still has the refit's residual share only, and a hand-set bpm or anchor still gives null.
- `BeatsFile` gains `cross_check_beats`, librosa's beat times after onset snap, so the cross-check and the spans can be worked out again without the audio.
- The job stages gain `check` after `meter`, where librosa runs and the confidence is worked out. That's the job status, not the report.

2.3 reports and beats files are upgraded when they're read by changing the version only: no spans, no cross-check and no second tracker's beats, and the segment confidences stay what they were. Older files go through the earlier steps first.
