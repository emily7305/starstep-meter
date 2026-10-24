"""Write a synthetic click track for checking the tool by hand.

Usage: python scripts/make_click_track.py click-120.wav [--bpm 120] [--lead 2.0] [--tail 2.0] [--beats 40] [--accent]

Prints the ground truth (first click, first downbeat, end of the last
click) so the result in the UI can be compared against it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# run from anywhere, the generator lives in tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.synth import ClickTrackSpec, click_track, write_wav  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--lead", type=float, default=2.0, help="leading silence in seconds")
    parser.add_argument("--tail", type=float, default=2.0, help="trailing silence in seconds")
    parser.add_argument("--beats", type=int, default=40)
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--noise-db", type=float, default=None, help="white noise floor in dbfs, off by default")
    # without accents every click looks the same and the tracker can't tell which one is beat 1
    parser.add_argument("--accent", action="store_true", help="louder, higher click on beat 1 of each bar")
    parser.add_argument("--beats-per-bar", type=int, default=4)
    args = parser.parse_args(argv)

    spec = ClickTrackSpec(
        bpm=args.bpm,
        beats=args.beats,
        lead_silence_s=args.lead,
        tail_silence_s=args.tail,
        sample_rate=args.sample_rate,
        noise_floor_db=args.noise_db,
        accent_downbeats=args.accent,
        beats_per_bar=args.beats_per_bar,
    )
    track = click_track(spec)
    write_wav(track, args.out)
    print(f"wrote {args.out}")
    print(f"  bpm         {spec.bpm:.2f}")
    print(f"  first click {track.content_start_ms:.3f} ms")
    if args.accent:
        print(f"  downbeats   every {spec.beats_per_bar} clicks from the first one")
    print(f"  last click  ends at {track.content_end_ms:.1f} ms")
    print(f"  duration    {track.duration_ms:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
