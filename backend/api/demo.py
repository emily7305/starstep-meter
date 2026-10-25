"""The demo track: a short click track with drums made right here, for trying the tool and the tour.

Nothing is downloaded and there's no real music in it. 128 bpm in 4/4 for 16 bars after half a
second of silence: kick on 1 and 3, snare on 2 and 4, hats on the 8ths and a click on every beat,
with beat 1 the loudest. Seeded, so every demo is the same file.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

DEMO_NAME = "demo click track.wav"
DEMO_BPM = 128.0
DEMO_BARS = 16
DEMO_LEAD_S = 0.5
SAMPLE_RATE = 44100
_TAIL_S = 1.0


def _decay(n: int, seconds: float, sample_rate: int) -> np.ndarray:
    return np.exp(-np.arange(n) / (seconds * sample_rate))


def _kick(sample_rate: int) -> np.ndarray:
    n = int(0.25 * sample_rate)
    t = np.arange(n) / sample_rate
    # a sweep from 120 down to 50 hz, the usual drum machine kick
    freq = 50.0 + 70.0 * np.exp(-t / 0.03)
    return np.sin(2 * np.pi * np.cumsum(freq) / sample_rate) * _decay(n, 0.08, sample_rate)


def _snare(sample_rate: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.18 * sample_rate)
    t = np.arange(n) / sample_rate
    body = 0.5 * np.sin(2 * np.pi * 190.0 * t) * _decay(n, 0.04, sample_rate)
    # first difference of white noise, a cheap high-pass
    noise = np.diff(rng.standard_normal(n + 1)) * 0.35 * _decay(n, 0.05, sample_rate)
    return body + noise


def _hat(sample_rate: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.05 * sample_rate)
    noise = np.diff(rng.standard_normal(n + 2), n=2) * 0.12
    return noise * _decay(n, 0.008, sample_rate)


def _click(sample_rate: int, freq: float) -> np.ndarray:
    n = int(0.02 * sample_rate)
    return np.sin(2 * np.pi * freq * np.arange(n) / sample_rate) * _decay(n, 0.004, sample_rate)


def demo_samples(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """The demo as mono float32, peak at -3 dBFS."""
    rng = np.random.default_rng(128)
    beat_s = 60.0 / DEMO_BPM
    beats = DEMO_BARS * 4
    out = np.zeros(int((DEMO_LEAD_S + beats * beat_s + _TAIL_S) * sample_rate))
    kick, snare, hat = _kick(sample_rate), _snare(sample_rate, rng), _hat(sample_rate, rng)
    accent, plain = _click(sample_rate, 1800.0), _click(sample_rate, 1200.0)

    def put(sound: np.ndarray, at_s: float, gain: float) -> None:
        i = int(round(at_s * sample_rate))
        end = min(len(out), i + len(sound))
        out[i:end] += gain * sound[: end - i]

    for k in range(beats):
        at = DEMO_LEAD_S + k * beat_s
        in_bar = k % 4
        # beat 1 louder than beat 3, or the bar could start on either kick
        put(kick if in_bar in (0, 2) else snare, at, {0: 1.0, 2: 0.5}.get(in_bar, 0.7))
        put(accent if in_bar == 0 else plain, at, 0.4 if in_bar == 0 else 0.15)
        put(hat, at, 0.5)
        put(hat, at + beat_s / 2, 0.3)
    peak = float(np.max(np.abs(out)))
    return (out * (10 ** (-3 / 20) / peak)).astype(np.float32)


def write_demo(path: Path) -> Path:
    sf.write(path, demo_samples(), SAMPLE_RATE, subtype="PCM_16")
    return path
