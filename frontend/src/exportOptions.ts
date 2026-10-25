// the export choice and the request it makes. the timing json is the report as it is, with
// beats.json in it only when asked for

export interface ExportChoice {
  beats: boolean;
}

export const DEFAULT_CHOICE: ExportChoice = { beats: false };

export function exportPath(jobId: string, choice: ExportChoice): string {
  const query = choice.beats ? "?beats=true" : "";
  return `/api/jobs/${encodeURIComponent(jobId)}/export${query}`;
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
