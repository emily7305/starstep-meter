"""Check that madmom imports and its downbeat tracker runs.

Usage: python scripts/check_madmom.py

Prints "madmom ok" plus the tracked beats, or the exact failure.
Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import sys
import traceback

import numpy as np

SAMPLE_RATE = 44100
BPM = 120.0
DURATION_S = 12.0
BEATS_PER_BAR = 4


def make_click_track() -> np.ndarray:
    # kept standalone on purpose so this script doesn't need the repo on sys.path
    n = int(DURATION_S * SAMPLE_RATE)
    audio = np.zeros(n, dtype=np.float32)
    click_len = int(0.03 * SAMPLE_RATE)
    t = np.arange(click_len) / SAMPLE_RATE
    beat_s = 60.0 / BPM
    i = 0
    while True:
        start = int(round((0.5 + i * beat_s) * SAMPLE_RATE))
        if start + click_len > n:
            break
        # higher, louder click on the downbeat so the tracker has something to find
        downbeat = i % BEATS_PER_BAR == 0
        freq = 1500.0 if downbeat else 1000.0
        amp = 0.9 if downbeat else 0.5
        audio[start:start + click_len] += amp * np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.008)
        i += 1
    return audio


def main() -> int:
    try:
        import madmom
        from madmom.audio.signal import Signal
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor
    except Exception:
        print("madmom import failed:")
        traceback.print_exc()
        return 1

    print(f"madmom {getattr(madmom, '__version__', '?')} imported, numpy {np.__version__}, python {sys.version.split()[0]}")

    try:
        signal = Signal(make_click_track(), sample_rate=SAMPLE_RATE, num_channels=1)
        activations = RNNDownBeatProcessor()(signal)
        tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
        beats = tracker(activations)
    except Exception:
        print("madmom downbeat tracking failed:")
        traceback.print_exc()
        return 1

    # beats is (n, 2): time in seconds, position in bar (1 = downbeat)
    print(f"madmom ok, {len(beats)} beats tracked")
    for time_s, position in beats[:8]:
        print(f"  {time_s * 1000.0:9.1f} ms  beat {int(position)}")
    if len(beats) > 1:
        bpm = 60.0 / float(np.median(np.diff(beats[:, 0])))
        print(f"  median tempo {bpm:.2f} bpm (generated at {BPM:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
