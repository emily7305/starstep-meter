"""Write a drum track for checking the half and double time feel by hand.

Usage: python scripts/make_drum_track.py drums-130.wav [--bpm 130] [--bars 48] [--lead 0.5] [--tail 1.0]
       [--sample-rate 44100] [--section BAR:COUNT:FEEL ...]

Prints the ground truth (first beat, each section in ms and the bpm it
should be charted at) so the result in the UI can be compared against it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import soundfile as sf

# run from anywhere, the generator lives in tests/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.synth import DrumTrackSpec, drum_track  # noqa: E402


def _section(text: str) -> tuple[int, int, str]:
    bar, _, rest = text.partition(":")
    count, _, feel = rest.partition(":")
    try:
        if feel not in ("half", "double"):
            raise ValueError(feel)
        return int(bar), int(count), feel
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected BAR:COUNT:FEEL like 16:8:half, got {text!r}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--bpm", type=float, default=130.0)
    parser.add_argument("--bars", type=int, default=48)
    parser.add_argument("--lead", type=float, default=0.5, help="leading silence in seconds")
    parser.add_argument("--tail", type=float, default=1.0, help="trailing silence in seconds")
    parser.add_argument("--sample-rate", type=int, default=44100)
    # half has the snare on beat 3 only, double a kick on every beat and the snare between
    parser.add_argument(
        "--section", type=_section, action="append", default=[], metavar="BAR:COUNT:FEEL", help="half or double time bars, repeatable"
    )
    args = parser.parse_args(argv)
    if any(bar < 0 or count < 1 or bar + count > args.bars for bar, count, _ in args.section):
        parser.error("a --section has to fit inside --bars")

    spec = DrumTrackSpec(
        bpm=args.bpm,
        bars=args.bars,
        lead_silence_s=args.lead,
        tail_silence_s=args.tail,
        sample_rate=args.sample_rate,
        sections=tuple(args.section),
    )
    track = drum_track(spec)
    # float like the cached test fixtures, so the wav is exactly what the tests generate
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.out, track.samples, spec.sample_rate, subtype="FLOAT")
    print(f"wrote {args.out}")
    print(f"  bpm         {spec.bpm:.2f}")
    print(f"  first beat  {track.first_beat_ms:.3f} ms")
    for (bar, count, feel), (start, end, _) in zip(spec.sections, track.sections_ms):
        charted = spec.bpm * (0.5 if feel == "half" else 2.0)
        print(f"  {feel:<12}bars {bar} to {bar + count}, {start:.3f} to {end:.3f} ms, charted at {charted:.2f} bpm")
    print(f"  duration    {track.duration_ms:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
