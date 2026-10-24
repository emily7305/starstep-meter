/* generated from shared/schema/timing_report.schema.json by npm run gen:types, don't edit by hand */

/**
 * path of the changed value, e.g. tempo_map/0/bpm
 */
export type Field = string;
export type JsonValue = unknown;
export type Timestamp = string;
export type Edits = Edit[];
export type Confidence = number | null;
export type Denominator = number;
export type Numerator = number;
export type Source = "auto" | "manual";
export type StartBar = number;
export type MeterMap = MeterSegment[];
export type SchemaVersion = "2.0";
export type EndMs = number;
export type Label = string;
export type Source1 = "auto" | "manual";
export type StartMs = number;
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
export type EndMs1 = number;
export type Source2 = "auto" | "manual";
/**
 * where this tempo starts, the first segment starts at trim.start_ms
 */
export type StartMs1 = number;
/**
 * end of the last audible sound
 */
export type EndMs2 = number;
/**
 * first audible sound
 */
export type StartMs2 = number;

export interface TimingReport {
  edits: Edits;
  meter_map: MeterMap;
  schema_version: SchemaVersion;
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
  numerator: Numerator;
  source: Source;
  start_bar: StartBar;
}
export interface Section {
  end_ms: EndMs;
  label: Label;
  source: Source1;
  start_ms: StartMs;
}
export interface AudioSource {
  codec: Codec;
  decoder_padding_samples: DecoderPaddingSamples;
  duration_ms: DurationMs;
  filename: Filename;
  sample_rate: SampleRate;
  sha256: Sha256;
}
export interface TempoSegment {
  anchor_ms: AnchorMs;
  bpm: Bpm;
  confidence: Confidence1;
  end_ms: EndMs1;
  source: Source2;
  start_ms: StartMs1;
}
export interface Trim {
  end_ms: EndMs2;
  start_ms: StartMs2;
}
