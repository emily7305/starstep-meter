// swing and gallop sections from the report: what they're called, and the note division a chart
// editor needs for them at the bpm their segment has now. the report gives the division at the
// bpm they were read on, and a segment halved or doubled since needs another one

import type { SubdivisionSection } from "./types/timingReport";

// bpms set by hand that aren't a small ratio of the one the notes were read on have no division
const MAX_RATIO_DENOMINATOR = 8;
const RATIO_TOLERANCE = 0.001;

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

// bpm over gridBpm as p/q with a small q, null when it isn't one
function simpleRatio(bpm: number, gridBpm: number): [number, number] | null {
  const ratio = bpm / gridBpm;
  for (let q = 1; q <= MAX_RATIO_DENOMINATOR; q += 1) {
    const p = Math.round(ratio * q);
    if (p > 0 && Math.abs(p / q - ratio) <= ratio * RATIO_TOLERANCE) return [p, q];
  }
  return null;
}

// the notes sit on multiples of 1/(division/4) of a grid beat, which is (bpm/gridBpm)/(division/4)
// of a beat at bpm. with the beat lines that's a step of 1/d beats, so the division is 4d.
// a swing read at 292 needs 1/12 there and 1/24 halved to 146, a gallop doubled needs 1/8
export function divisionAt(division: number, gridBpm: number, bpm: number): number | null {
  const ratio = simpleRatio(bpm, gridBpm);
  if (ratio === null || division % 4 !== 0) return null;
  const [p, q] = ratio;
  const num = p * 4;
  const den = q * division;
  return 4 * (den / gcd(num, den));
}

// 12 and 24 are triplet based, 16 straight
function onTriplets(section: SubdivisionSection): boolean {
  return section.division % 3 === 0;
}

export function feelKindText(section: SubdivisionSection): string {
  switch (section.kind) {
    case "swing":
      return `swing ${section.ratio.toFixed(2)}:1`;
    case "gallop":
      return onTriplets(section) ? "gallop on triplets" : "gallop, 8th-16th-16th";
    case "reverse_gallop":
      return onTriplets(section) ? "reverse gallop on triplets" : "reverse gallop, 16th-16th-8th";
  }
}

export function divisionText(division: number | null): string {
  return division === null ? "no simple division at this bpm" : `1/${division}`;
}
