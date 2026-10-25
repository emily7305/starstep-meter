/* generated from shared/schema/timing_report.schema.json by npm run gen:types, don't edit by hand */

/**
 * share of compared beats where the second tracker had one close by, null without one
 */
export type Agreement = number | null;
/**
 * residual_share * (1 - w + w * agreement), w = 0.5, or residual_share without a cross-check
 */
export type Confidence = number;
export type EndMs = number;
/**
 * under the threshold the timeline shades at
 */
export type Low = boolean;
/**
 * share of its tracked beats within 10 ms of the grid, a felt section's beats count as min(1, fit). off-beat runs and their ramps are left out, null when that leaves nothing
 */
export type ResidualShare = number | null;
export type StartMs = number;
/**
 * confidence over stretches of the auto tempo segments, sorted by time. analysis output, edits don't change it and a re-analysis replaces it
 */
export type ConfidenceSpans = ConfidenceSpan[];
export type MaxDisagreementMs = number;
/**
 * beats compared, felt sections and off-beat runs left out
 */
export type Compared = number;
/**
 * median distance between the two trackers' beats, null with too few beats to compare
 */
export type DisagreementMs = number | null;
export type EndMs1 = number;
/**
 * disagreement_ms is over max_disagreement_ms
 */
export type Flagged = boolean;
export type StartMs1 = number;
/**
 * one per tempo segment the analysis found, not following later edits
 */
export type Segments = CrossCheckSegment[];
export type Tracker = "librosa";
/**
 * the deepest path that holds everything the change touched, e.g. tempo_map/0/bpm. with one changed value old and new are that value, with several they're objects keyed by each value's path under field, and an empty field is the report itself
 */
export type Field = string;
export type JsonValue = unknown;
export type Timestamp = string;
export type Edits = Edit[];
export type Confidence1 = number | null;
export type Denominator = number;
/**
 * where it stops, the same value as the next meter segment's start_ms
 */
export type EndMs2 = number;
export type Numerator = number;
export type Source = "auto" | "manual";
/**
 * where this meter starts, the first starts at tempo_map[0].start_ms. inside a tempo segment it's a bar line and bars restart there, at a tempo segment's start the segment's anchor is bar 1
 */
export type StartMs2 = number;
export type MeterMap = MeterSegment[];
export type EndMs3 = number;
/**
 * bpm of the tempo segment the suggestion was made on
 */
export type GridBpm = number;
/**
 * half: the span feels like half the grid's tempo, double: twice it, fold: a first or last stretch that may be its neighbour's tempo the analysis didn't fold in
 */
export type Kind = "half" | "double" | "fold";
/**
 * how clear the evidence is, 1 is as clear as it gets
 */
export type Score = number;
/**
 * a bar line, or the start of the tempo segment for a fold
 */
export type StartMs3 = number;
export type Status = "open" | "applied" | "dismissed";
export type SuggestedBpm = number;
/**
 * places where a chart may write the pulse at another tempo (half or double time feel) or fold an edge into its neighbour. never applied by the analysis, an edit applies or dismisses each one
 */
export type NotationSuggestions = NotationSuggestion[];
/**
 * tracked beats in the run
 */
export type Beats = number;
/**
 * last tracked beat of the run
 */
export type EndMs4 = number;
/**
 * first tracked beat of the run
 */
export type StartMs4 = number;
/**
 * stretches where the analysis found the tracked beats half a beat off the tempo map's grid. the grid is on the real beats there, the tracker followed the off-beat. analysis output, edits don't change it
 */
export type OffbeatRuns = OffbeatRun[];
export type SchemaVersion = "2.5";
export type EndMs5 = number;
export type Label = string;
export type Source1 = "auto" | "manual";
export type StartMs5 = number;
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
export type Sha256 = string;
/**
 * notes per 4/4 measure a chart editor needs for them at grid_bpm, 12 is 1/12. twice that with the bpm halved
 */
export type Division = number;
/**
 * a bar line, or the end of the tempo segment
 */
export type EndMs6 = number;
/**
 * bpm of the tempo segment it was read on
 */
export type GridBpm1 = number;
/**
 * swing: long-short 8ths, gallop: 8th-16th-16th, reverse_gallop: 16th-16th-8th, the gallops on a straight or a triplet base
 */
export type Kind1 = "swing" | "gallop" | "reverse_gallop";
/**
 * the long note over the short one, 2 for a 2:1 swing or a straight gallop, 4 for a triplet gallop
 */
export type Ratio = number;
/**
 * how clear the notes and the empty positions are, 1 is as clear as it gets
 */
export type Score1 = number;
/**
 * a bar line, or the start of the tempo segment
 */
export type StartMs6 = number;
/**
 * stretches where the notes between the beats are uneven (swing, gallop), with the division a chart editor needs for them. suggestions only, nothing applies them. analysis output, edits don't change it and a re-analysis replaces it
 */
export type SubdivisionSections = SubdivisionSection[];
/**
 * @minItems 1
 */
export type TempoMap = [TempoSegment, ...TempoSegment[]];
/**
 * a downbeat on this segment's grid, which is anchor_ms + k * 60000 / bpm. the first segment's anchor is the song's first downbeat
 */
export type AnchorMs = number;
export type Bpm = number;
/**
 * residual share times cross-check agreement over the segment, like confidence_spans, halved for the librosa fallback. a refit after a split or merge has the refit's residual share only, null when the bpm or anchor was set by hand
 */
export type Confidence2 = number | null;
/**
 * where it stops, the same value as the next segment's start_ms
 */
export type EndMs7 = number;
/**
 * what the stretch fitted to on its own
 */
export type Bpm1 = number;
export type EndMs8 = number;
/**
 * share of its beats on the segment's grid (lines, halves, thirds) over the share on its own grid
 */
export type Fit = number;
/**
 * its bpm over the segment's, near enough, e.g. 3/4 for a triplet feel or 2/3 for a dotted one
 */
export type Ratio1 = string;
export type StartMs7 = number;
/**
 * felt tempo sections (dotted, triplet feel) inside this segment that the analysis kept on its grid, splitting at a section's start_ms and end_ms gives it back its own tempo
 */
export type RatioMerged = RatioMergedSection[];
export type Source2 = "auto" | "manual";
/**
 * where this tempo starts, the first segment starts at trim.start_ms
 */
export type StartMs8 = number;
/**
 * end of the last audible sound
 */
export type EndMs9 = number;
/**
 * first audible sound
 */
export type StartMs9 = number;

export interface TimingReport {
  confidence_spans: ConfidenceSpans;
  /**
   * the second tracker's verdict per tempo segment, null when it didn't run
   */
  cross_check: CrossCheck | null;
  edits: Edits;
  meter_map: MeterMap;
  notation_suggestions: NotationSuggestions;
  offbeat_runs: OffbeatRuns;
  schema_version: SchemaVersion;
  sections: Sections;
  source: AudioSource;
  subdivision_sections: SubdivisionSections;
  tempo_map: TempoMap;
  trim: Trim;
}
export interface ConfidenceSpan {
  agreement: Agreement;
  confidence: Confidence;
  end_ms: EndMs;
  low: Low;
  residual_share: ResidualShare;
  start_ms: StartMs;
}
export interface CrossCheck {
  max_disagreement_ms: MaxDisagreementMs;
  segments: Segments;
  tracker: Tracker;
}
export interface CrossCheckSegment {
  compared: Compared;
  disagreement_ms: DisagreementMs;
  end_ms: EndMs1;
  flagged: Flagged;
  start_ms: StartMs1;
}
export interface Edit {
  field: Field;
  new: JsonValue;
  old: JsonValue;
  timestamp: Timestamp;
}
export interface MeterSegment {
  confidence: Confidence1;
  denominator: Denominator;
  end_ms: EndMs2;
  numerator: Numerator;
  source: Source;
  start_ms: StartMs2;
}
export interface NotationSuggestion {
  end_ms: EndMs3;
  grid_bpm: GridBpm;
  kind: Kind;
  score: Score;
  start_ms: StartMs3;
  status: Status;
  suggested_bpm: SuggestedBpm;
}
export interface OffbeatRun {
  beats: Beats;
  end_ms: EndMs4;
  start_ms: StartMs4;
}
export interface Section {
  end_ms: EndMs5;
  label: Label;
  source: Source1;
  start_ms: StartMs5;
}
export interface AudioSource {
  codec: Codec;
  decoder_padding_samples: DecoderPaddingSamples;
  duration_ms: DurationMs;
  filename: Filename;
  sample_rate: SampleRate;
  sha256: Sha256;
}
export interface SubdivisionSection {
  division: Division;
  end_ms: EndMs6;
  grid_bpm: GridBpm1;
  kind: Kind1;
  ratio: Ratio;
  score: Score1;
  start_ms: StartMs6;
}
export interface TempoSegment {
  anchor_ms: AnchorMs;
  bpm: Bpm;
  confidence: Confidence2;
  end_ms: EndMs7;
  ratio_merged: RatioMerged;
  source: Source2;
  start_ms: StartMs8;
}
export interface RatioMergedSection {
  bpm: Bpm1;
  end_ms: EndMs8;
  fit: Fit;
  ratio: Ratio1;
  start_ms: StartMs7;
}
export interface Trim {
  end_ms: EndMs9;
  start_ms: StartMs9;
}
