"""Write a synthetic click track for checking the tool by hand.

Usage: python scripts/make_click_track.py click-120.wav [--bpm 120] [--lead 2.0] [--tail 2.0] [--beats 40] [--accent]
       [--change BEAT:BPM ...] [--meter BEAT:BEATS_PER_BAR ...] [--rhythm BEAT:COUNT:POSITIONS ...]

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


def _change(text: str) -> tuple[int, float]:
    beat, _, bpm = text.partition(":")
    try:
        return int(beat), float(bpm)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected BEAT:BPM like 64:200, got {text!r}") from None


def _meter(text: str) -> tuple[int, int]:
    beat, _, beats_per_bar = text.partition(":")
    try:
        return int(beat), int(beats_per_bar)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected BEAT:BEATS_PER_BAR like 64:7, got {text!r}") from None


def _rhythm(text: str) -> tuple[int, int, tuple[float, ...]]:
    beat, count, positions = (text.split(":") + ["", ""])[:3]
    try:
        return int(beat), int(count), tuple(float(p) for p in positions.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected BEAT:COUNT:POSITIONS like 128:32:0,1.5,3, got {text!r}") from None


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
    # click BEAT (counted from 0) is the first one at the new tempo
    parser.add_argument("--change", type=_change, action="append", default=[], metavar="BEAT:BPM", help="tempo change, repeatable")
    # click BEAT (counted from 0) is a downbeat and bars from it on have the new length
    parser.add_argument(
        "--meter", type=_meter, action="append", default=[], metavar="BEAT:BEATS_PER_BAR", help="bar length change, repeatable"
    )
    # COUNT beats from click BEAT where the clicks play POSITIONS (in beats) of every 4 beat bar
    # instead, the tempo underneath doesn't change. 0,1.5,3 is a dotted 3-3-2 bar
    parser.add_argument(
        "--rhythm", type=_rhythm, action="append", default=[], metavar="BEAT:COUNT:POSITIONS", help="felt rhythm, repeatable"
    )
    args = parser.parse_args(argv)
    if any(not 0 < beat < args.beats for beat, _ in args.change):
        parser.error("a --change beat has to be between 1 and --beats - 1")
    if any(not 0 < beat < args.beats for beat, _ in args.meter):
        parser.error("a --meter beat has to be between 1 and --beats - 1")
    if any(beats_per_bar < 1 for _, beats_per_bar in args.meter):
        parser.error("a --meter bar length has to be at least 1")
    if any(beat < 0 or count < 1 or beat + count > args.beats for beat, count, _ in args.rhythm):
        parser.error("a --rhythm section has to fit inside --beats")

    spec = ClickTrackSpec(
        bpm=args.bpm,
        beats=args.beats,
        lead_silence_s=args.lead,
        tail_silence_s=args.tail,
        sample_rate=args.sample_rate,
        noise_floor_db=args.noise_db,
        accent_downbeats=args.accent,
        beats_per_bar=args.beats_per_bar,
        tempo_changes=tuple(args.change),
        meter_changes=tuple(args.meter),
        patterns=tuple(args.rhythm),
    )
    track = click_track(spec)
    write_wav(track, args.out)
    print(f"wrote {args.out}")
    print(f"  bpm         {spec.bpm:.2f}")
    for (beat, bpm), at in zip(sorted(spec.tempo_changes), track.change_ms):
        print(f"  change      {bpm:.2f} bpm from click {beat}, at {at:.3f} ms")
    period_ms = 60000.0 / spec.bpm
    for beat, count, positions in spec.patterns:
        # only right without a tempo change before it, which is how the readme check uses it
        start = track.content_start_ms + beat * period_ms
        print(f"  rhythm      {','.join(f'{p:g}' for p in positions)} from beat {beat} to {beat + count}, about {start:.1f} to {start + count * period_ms:.1f} ms")
    print(f"  first click {track.content_start_ms:.3f} ms")
    if args.accent:
        until = ", until the first meter change" if spec.meter_changes else ""
        print(f"  downbeats   every {spec.beats_per_bar} clicks from the first one{until}")
        for beat, beats_per_bar in sorted(spec.meter_changes):
            print(f"  meter       {beats_per_bar} beats per bar from click {beat}, at {track.onsets_ms[beat]:.3f} ms")
    print(f"  last click  ends at {track.content_end_ms:.1f} ms")
    print(f"  duration    {track.duration_ms:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
