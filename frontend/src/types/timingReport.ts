/* generated from shared/schema/timing_report.schema.json by npm run gen:types, don't edit by hand */

export type BeatOffsetMs = number | null;
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
export type SchemaVersion = "1.0";
export type EndMs = number;
export type Label = string;
export type Source1 = "auto" | "manual";
export type StartMs = number;
export type Sections = Section[];
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
export type Bpm = number;
export type Confidence1 = number | null;
export type Source2 = "auto" | "manual";
export type StartMs1 = number;
export type TempoMap = TempoSegment[];
/**
 * end of the last audible sound
 */
export type EndMs1 = number;
/**
 * first audible sound
 */
export type StartMs2 = number;

export interface TimingReport {
  beat_offset_ms: BeatOffsetMs;
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
  duration_ms: DurationMs;
  filename: Filename;
  sample_rate: SampleRate;
  sha256: Sha256;
}
export interface TempoSegment {
  bpm: Bpm;
  confidence: Confidence1;
  source: Source2;
  start_ms: StartMs1;
}
export interface Trim {
  end_ms: EndMs1;
  start_ms: StartMs2;
}
