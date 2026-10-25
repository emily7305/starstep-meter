// the export choices and the request they make. timing is the report as it is (beats only when
// asked for), sonolus the values a Sonolus level needs, with the decoder compensation in bgmOffset

import type { AudioSource } from "./types/timingReport";

export type ExportPreset = "timing" | "sonolus";

export interface ExportChoice {
  preset: ExportPreset;
  beats: boolean;
  compensationMs: number;
}

export interface CompensationPreset {
  label: string;
  ms: number;
}

export const DEFAULT_CHOICE: ExportChoice = { preset: "timing", beats: false, compensationMs: 0 };
// same limit as the server, past it it's a typo and not a decoder
export const MAX_COMPENSATION_MS = 1000;

export function paddingMs(source: AudioSource): number {
  return Math.round((source.decoder_padding_samples / source.sample_rate) * 1e6) / 1000;
}

// 0 for a player whose decoder honours the gapless info, the padding for one that doesn't
export function compensationPresets(source: AudioSource): CompensationPreset[] {
  const out: CompensationPreset[] = [{ label: "0 ms", ms: 0 }];
  const padding = paddingMs(source);
  if (padding > 0) out.push({ label: `${padding.toFixed(3)} ms, ${source.decoder_padding_samples} padding samples`, ms: padding });
  return out;
}

export function validCompensation(ms: number): boolean {
  return Number.isFinite(ms) && Math.abs(ms) <= MAX_COMPENSATION_MS;
}

export function exportPath(jobId: string, choice: ExportChoice): string {
  const params = new URLSearchParams();
  if (choice.preset === "sonolus") {
    params.set("preset", "sonolus");
    if (choice.compensationMs !== 0) params.set("decoder_compensation_ms", String(choice.compensationMs));
  } else if (choice.beats) {
    params.set("beats", "true");
  }
  const query = params.toString();
  return `/api/jobs/${encodeURIComponent(jobId)}/export${query ? `?${query}` : ""}`;
}

// the server's content-disposition, filename* has the real name and filename an ascii stand-in
export function downloadName(disposition: string | null, fallback: string): string {
  if (disposition === null) return fallback;
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  if (encoded !== undefined) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // a broken escape, the plain one is next
    }
  }
  return /filename="([^"]+)"/i.exec(disposition)?.[1] ?? fallback;
}
