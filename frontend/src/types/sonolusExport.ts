/* generated from shared/schema/sonolus_export.schema.json by npm run gen:types, don't edit by hand */

/**
 * the same changes as level_data, with times
 *
 * @minItems 1
 */
export type BpmChanges = [SonolusBpmChange, ...SonolusBpmChange[]];
export type Beat = number;
export type Bpm = number;
/**
 * where the change is on the report's timeline (ffmpeg's decode), before decoder compensation
 */
export type TimeMs = number;
/**
 * how much later than ffmpeg's timeline the player's decoder plays the audio, already in bgmOffset
 */
export type DecoderCompensationMs = number;
export type ExportedAt = string;
/**
 * the report's source filename, for display only
 */
export type Filename = string;
/**
 * the beat of tempo_map[0].anchor_ms, the song's first downbeat
 */
export type FirstDownbeatBeat = number;
export type Kind = "sonolus";
/**
 * seconds into the bgm file at level time 0, which is beat 0. the bgm is at level time + bgmOffset
 */
export type Bgmoffset = number;
export type Archetype = string;
export type Name = string;
export type Value = number;
export type Data = SonolusDataValue[];
/**
 * one #BPM_CHANGE per tempo, with #BEAT and #BPM. an engine's own entities (initialization, stage, notes) go next to these
 */
export type Entities = SonolusEntity[];
/**
 * the source file the report belongs to
 */
export type Sha256 = string;
/**
 * not part of Sonolus level data, which has no time signature archetype. for the chart editor. a bar cut short by a tempo change or a meter split gets its own entry
 *
 * @minItems 1
 */
export type TimeSignatures = [SonolusTimeSignature, ...SonolusTimeSignature[]];
/**
 * the bar line this signature starts on
 */
export type Beat1 = number;
export type Denominator = number;
export type Numerator = number;

export interface SonolusExport {
  bpm_changes: BpmChanges;
  decoder_compensation_ms: DecoderCompensationMs;
  exported_at: ExportedAt;
  filename: Filename;
  first_downbeat_beat: FirstDownbeatBeat;
  kind: Kind;
  level_data: SonolusLevelData;
  sha256: Sha256;
  time_signatures: TimeSignatures;
}
export interface SonolusBpmChange {
  beat: Beat;
  bpm: Bpm;
  time_ms: TimeMs;
}
export interface SonolusLevelData {
  bgmOffset: Bgmoffset;
  entities: Entities;
}
export interface SonolusEntity {
  archetype: Archetype;
  data: Data;
}
export interface SonolusDataValue {
  name: Name;
  value: Value;
}
export interface SonolusTimeSignature {
  beat: Beat1;
  denominator: Denominator;
  numerator: Numerator;
}
