/* generated from shared/schema/beats.schema.json by npm run gen:types, don't edit by hand */

export type Bar = number;
export type BeatInBar = number;
export type IsDownbeat = boolean;
/**
 * beat time as the tracker reported it, before onset snap
 */
export type RawTimeMs = number;
/**
 * time_ms minus the fitted grid at this beat
 */
export type ResidualMs = number;
/**
 * beat time after onset snap
 */
export type TimeMs = number;
export type Beats = Beat[];
export type SchemaVersion = "1.1";
/**
 * same file as the report it belongs to
 */
export type Sha256 = string;
export type Tracker = "madmom" | "librosa";

export interface BeatsFile {
  beats: Beats;
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
