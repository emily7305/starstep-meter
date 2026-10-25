// dropping a song anywhere on the page. the server checks the file again, this is only so a
// dropped text file gets a plain message instead of a 415

export const AUDIO_EXTENSIONS = [".mp3", ".wav", ".flac", ".ogg", ".m4a"] as const;

export function isAudioName(name: string): boolean {
  const lower = name.toLowerCase();
  return AUDIO_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

// a drag of text or a link from another tab isn't a file, the page shouldn't light up for it
export function carriesFiles(types: readonly string[] | DOMStringList | null | undefined): boolean {
  if (types === null || types === undefined) return false;
  return Array.from(types as ArrayLike<string>).includes("Files");
}

export const NOT_AUDIO = "not an audio file, use mp3, wav, flac, ogg or m4a";
