/* generated from shared/schema/timing_export.schema.json by npm run gen:types, don't edit by hand */

export type Bar = number;
export type BeatInBar = number;
export type IsDownbeat = boolean;
/**
 * beat time as the tracker reported it, before bias correction and onset snap. halfway between two tracker beats when the octave check doubled the tempo
 */
export type RawTimeMs = number;
/**
 * time_ms minus its tempo segment's fitted grid at this beat. a beat in a ratio merged section or an off-beat run is measured against the subdivision it sits on, half a beat for an off-beat run
 */
export type ResidualMs = number;
/**
 * beat time after onset snap
 */
export type TimeMs = number;
export type Beats1 = Beat[];
/**
 * 5-16 khz, hats, cymbals and the snare's noise
 */
export type High = number;
/**
 * 30-150 hz, kick and bass attacks
 */
export type Low = number;
/**
 * 150-3000 hz, snare body and most other attacks
 */
export type Mid = number;
/**
 * a grid line or half line of the analysis' tempo map
 */
export type TimeMs1 = number;
/**
 * band onset strengths at every grid line and half line of the analysis' tempo map, plus the lines the fold check carried into an edge stretch, sorted by time. what the notation suggestions are worked out from, so they can be checked again without the audio
 */
export type GridFeatures = GridFeature[];
/**
 * what the octave check did to the tracker's tempo, mixed when it differs between tempo segments, see docs/decisions.md
 */
export type Octave = "kept" | "doubled" | "halved" | "mixed";
export type SchemaVersion = "2.3";
/**
 * same file as the report it belongs to
 */
export type Sha256 = string;
export type Tracker = "madmom" | "librosa";
export type ExportedAt = string;
export type Kind = "timing";
/**
 * the deepest path that holds everything the change touched, e.g. tempo_map/0/bpm. with one changed value old and new are that value, with several they're objects keyed by each value's path under field, and an empty field is the report itself
 */
export type Field = string;
export type JsonValue = unknown;
export type Timestamp = string;
export type Edits = Edit[];
export type Confidence = number | null;
export type Denominator = number;
/**
 * where it stops, the same value as the next meter segment's start_ms
 */
export type EndMs = number;
export type Numerator = number;
export type Source = "auto" | "manual";
/**
 * where this meter starts, the first starts at tempo_map[0].start_ms. inside a tempo segment it's a bar line and bars restart there, at a tempo segment's start the segment's anchor is bar 1
 */
export type StartMs = number;
export type MeterMap = MeterSegment[];
export type EndMs1 = number;
/**
 * bpm of the tempo segment the suggestion was made on
 */
export type GridBpm = number;
/**
 * half: the span feels like half the grid's tempo, double: twice it, fold: a first or last stretch that may be its neighbour's tempo the analysis didn't fold in
 */
export type Kind1 = "half" | "double" | "fold";
/**
 * how clear the evidence is, 1 is as clear as it gets
 */
export type Score = number;
/**
 * a bar line, or the start of the tempo segment for a fold
 */
export type StartMs1 = number;
export type Status = "open" | "applied" | "dismissed";
export type SuggestedBpm = number;
/**
 * places where a chart may write the pulse at another tempo (half or double time feel) or fold an edge into its neighbour. never applied by the analysis, an edit applies or dismisses each one
 */
export type NotationSuggestions = NotationSuggestion[];
/**
 * tracked beats in the run
 */
export type Beats2 = number;
/**
 * last tracked beat of the run
 */
export type EndMs2 = number;
/**
 * first tracked beat of the run
 */
export type StartMs2 = number;
/**
 * stretches where the analysis found the tracked beats half a beat off the tempo map's grid. the grid is on the real beats there, the tracker followed the off-beat. analysis output, edits don't change it
 */
export type OffbeatRuns = OffbeatRun[];
export type SchemaVersion1 = "2.3";
export type EndMs3 = number;
export type Label = string;
export type Source1 = "auto" | "manual";
export type StartMs3 = number;
export type Sections = Section[];
/**
 * codec of the first audio stream as ffprobe names it, e.g. mp3, aac, vorbis
 */
export type Codec = string;
/**
 * samples a decoder that ignores gapless info plays before ffmpeg's first sample, 0 if not applicable
 */
export type DecoderPaddingSamples = number;
/**
 * length of the decoded audio
 */
export type DurationMs = number;
/**
 * original upload name, for display only
 */
export type Filename = string;
/**
 * sample rate of the decoded audio in Hz
 */
export type SampleRate = number;
/**
 * sha256 of the original file, not the decoded wav
 */
export type Sha2561 = string;
/**
 * @minItems 1
 */
export type TempoMap = [TempoSegment, ...TempoSegment[]];
/**
 * a downbeat on this segment's grid, which is anchor_ms + k * 60000 / bpm. the first segment's anchor is the song's first downbeat
 */
export type AnchorMs = number;
export type Bpm = number;
export type Confidence1 = number | null;
/**
 * where it stops, the same value as the next segment's start_ms
 */
export type EndMs4 = number;
/**
 * what the stretch fitted to on its own
 */
export type Bpm1 = number;
export type EndMs5 = number;
/**
 * share of its beats on the segment's grid (lines, halves, thirds) over the share on its own grid
 */
export type Fit = number;
/**
 * its bpm over the segment's, near enough, e.g. 3/4 for a triplet feel or 2/3 for a dotted one
 */
export type Ratio = string;
export type StartMs4 = number;
/**
 * felt tempo sections (dotted, triplet feel) inside this segment that the analysis kept on its grid, splitting at a section's start_ms and end_ms gives it back its own tempo
 */
export type RatioMerged = RatioMergedSection[];
export type Source2 = "auto" | "manual";
/**
 * where this tempo starts, the first segment starts at trim.start_ms
 */
export type StartMs5 = number;
/**
 * end of the last audible sound
 */
export type EndMs6 = number;
/**
 * first audible sound
 */
export type StartMs6 = number;

export interface TimingExport {
  beats?: Beats;
  exported_at: ExportedAt;
  kind: Kind;
  report: TimingReport;
}
/**
 * the beats file of the same analysis, only there when the export asked for it
 */
export interface Beats {
  beats: Beats1;
  grid_features: GridFeatures;
  octave: Octave;
  schema_version: SchemaVersion;
  sha256: Sha256;
  tracker: Tracker;
}
export interface Beat {
  bar: Bar;
  beat_in_bar: BeatInBar;
  is_downbeat: IsDownbeat;
  raw_time_ms: RawTimeMs;
  residual_ms: ResidualMs;
  time_ms: TimeMs;
}
export interface GridFeature {
  high: High;
  low: Low;
  mid: Mid;
  time_ms: TimeMs1;
}
export interface TimingReport {
  edits: Edits;
  meter_map: MeterMap;
  notation_suggestions: NotationSuggestions;
  offbeat_runs: OffbeatRuns;
  schema_version: SchemaVersion1;
  sections: Sections;
  source: AudioSource;
  tempo_map: TempoMap;
  trim: Trim;
}
export interface Edit {
  field: Field;
  new: JsonValue;
  old: JsonValue;
  timestamp: Timestamp;
}
export interface MeterSegment {
  confidence: Confidence;
  denominator: Denominator;
  end_ms: EndMs;
  numerator: Numerator;
  source: Source;
  start_ms: StartMs;
}
export interface NotationSuggestion {
  end_ms: EndMs1;
  grid_bpm: GridBpm;
  kind: Kind1;
  score: Score;
  start_ms: StartMs1;
  status: Status;
  suggested_bpm: SuggestedBpm;
}
export interface OffbeatRun {
  beats: Beats2;
  end_ms: EndMs2;
  start_ms: StartMs2;
}
export interface Section {
  end_ms: EndMs3;
  label: Label;
  source: Source1;
  start_ms: StartMs3;
}
export interface AudioSource {
  codec: Codec;
  decoder_padding_samples: DecoderPaddingSamples;
  duration_ms: DurationMs;
  filename: Filename;
  sample_rate: SampleRate;
  sha256: Sha2561;
}
export interface TempoSegment {
  anchor_ms: AnchorMs;
  bpm: Bpm;
  confidence: Confidence1;
  end_ms: EndMs4;
  ratio_merged: RatioMerged;
  source: Source2;
  start_ms: StartMs5;
}
export interface RatioMergedSection {
  bpm: Bpm1;
  end_ms: EndMs5;
  fit: Fit;
  ratio: Ratio;
  start_ms: StartMs4;
}
export interface Trim {
  end_ms: EndMs6;
  start_ms: StartMs6;
}
