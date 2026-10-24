// japanese glyphs for song titles, loaded only when a name actually has some
// the css alone is over 100 KB of @font-face rules, too much to put in front of first paint
// every rule has a unicode-range, so the browser then only fetches the slices it needs

// kana, cjk punctuation, kanji, fullwidth forms
const JAPANESE = /[　-ヿ㐀-䶿一-鿿＀-￯]/;

let loading: Promise<unknown> | null = null;

export function hasJapanese(text: string): boolean {
  return JAPANESE.test(text);
}

export function ensureJapaneseFont(text: string | null | undefined): void {
  if (loading !== null || !text || !hasJapanese(text)) return;
  // only 400, filenames are the only japanese text and they're all regular weight
  loading = import("@fontsource/m-plus-rounded-1c/400.css").catch(() => {
    // a failed load falls back to the system font, allow another try later
    loading = null;
  });
}
