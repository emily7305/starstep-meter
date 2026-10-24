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
