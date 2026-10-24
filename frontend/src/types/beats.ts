/* generated from shared/schema/beats.schema.json by npm run gen:types, don't edit by hand */

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
export type Beats = Beat[];
/**
 * what the octave check did to the tracker's tempo, mixed when it differs between tempo segments, see docs/decisions.md
 */
export type Octave = "kept" | "doubled" | "halved" | "mixed";
export type SchemaVersion = "2.2";
/**
 * same file as the report it belongs to
 */
export type Sha256 = string;
export type Tracker = "madmom" | "librosa";

export interface BeatsFile {
  beats: Beats;
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
