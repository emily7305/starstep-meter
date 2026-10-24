// canvas can't use css custom properties, so read the palette from styles.css once
export interface Palette {
  ink: string;
  inkSoft: string;
  inkFaint: string;
  line: string;
  bgSunk: string;
  accent: string;
  mint: string;
  fontMono: string;
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function readPalette(): Palette {
  return {
    ink: cssVar("--ink", "#3b1f3f"),
    inkSoft: cssVar("--ink-soft", "#6f5a73"),
    inkFaint: cssVar("--ink-faint", "#a796a9"),
    line: cssVar("--line", "#dccfdc"),
    bgSunk: cssVar("--bg-sunk", "#ebe4ec"),
    accent: cssVar("--accent", "#e0136f"),
    mint: cssVar("--mint", "#3cc2a4"),
    fontMono: cssVar("--font-mono", "monospace"),
  };
}
