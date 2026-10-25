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
 * the second tracker's beats after onset snap, in ms, empty when it didn't run. timing only, the cross-check and the confidence can be worked out again from them without the audio
 */
export type CrossCheckBeats = number[];
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
export type SchemaVersion = "2.4";
/**
 * same file as the report it belongs to
 */
export type Sha256 = string;
export type Tracker = "madmom" | "librosa";

export interface BeatsFile {
  beats: Beats;
  cross_check_beats: CrossCheckBeats;
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
