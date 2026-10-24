"""Beat tracking: beat times and downbeats over the trimmed region.

madmom's downbeat tracker when it's installed, librosa's beat tracker as a
fallback. librosa has no downbeats, so its first beat is taken as beat 1 of
a 4/4 bar and the result is marked lower confidence.
"""

from __future__ import annotations

import functools
import importlib.util
from dataclasses import dataclass
from typing import Literal

import librosa
import numpy as np

from backend.analysis.tempo import estimate_tempo, onset_hop
from backend.analysis.tempo_range import TempoRange

Tracker = Literal["madmom", "librosa"]
TrackerChoice = Literal["auto", "madmom", "librosa"]

# madmom's networks were trained at 44.1 khz, and it only relabels an array's rate, never resamples it
MADMOM_SAMPLE_RATE = 44100
MADMOM_FPS = 100
MADMOM_BEATS_PER_BAR = (3, 4)
# a little audio either side of the trim points so the network sees the first attack in context
PAD_S = 0.5
# raw madmom beats come up to ~20 ms before the attack, so a beat just ahead of the trim start is real
EDGE_TOLERANCE_MS = 50.0
# median of madmom's raw beat minus the click onset, over 2480 beats in 48 synthetic tracks with
# random bpm (70-300) and lead, so the 10 ms frame lands at a random phase. see docs/decisions.md
MADMOM_BIAS_MS = -11.8
# what the librosa fallback assumes, there's no meter detection yet
FALLBACK_BEATS_PER_BAR = 4
MIN_BEATS = 4


class BeatTrackingError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrackedBeats:
    times_ms: np.ndarray
    # 1-based position in the bar, 1 is a downbeat
    positions: np.ndarray
    tracker: Tracker
    # false for librosa, where positions are a guess from the beat order
    downbeats_known: bool


def madmom_available() -> bool:
    # find_spec only looks, the import itself is slow
    return importlib.util.find_spec("madmom") is not None


@functools.lru_cache(maxsize=1)
def madmom_import_error() -> str | None:
    # installed doesn't mean it imports, the pypi 0.16.1 build wants pkg_resources. the import takes
    # about a second and can't change while the process runs, so it's tried once
    if not madmom_available():
        return None
    try:
        import madmom  # noqa: F401
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor  # noqa: F401
    except Exception as exc:
        # not only ImportError, a build that doesn't match numpy can raise AttributeError
        return f"{type(exc).__name__}: {exc}"
    return None


def _region(samples: np.ndarray, sample_rate: int, start_ms: float, end_ms: float) -> tuple[np.ndarray, int]:
    pad = int(round(PAD_S * sample_rate))
    lo = max(0, int(round(start_ms / 1000.0 * sample_rate)) - pad)
    hi = min(len(samples), int(round(end_ms / 1000.0 * sample_rate)) + pad)
    return samples[lo:hi], lo


def _track_madmom(region: np.ndarray, sample_rate: int, tempo_range: TempoRange) -> tuple[np.ndarray, np.ndarray]:
    from madmom.audio.signal import Signal
    from madmom.features.downbeats import DBNDownBeatTrackingProcessor, RNNDownBeatProcessor

    if sample_rate != MADMOM_SAMPLE_RATE:
        # soxr is linear phase, so this doesn't shift anything in time
        region = librosa.resample(region, orig_sr=sample_rate, target_sr=MADMOM_SAMPLE_RATE, res_type="soxr_hq")
    signal = Signal(np.ascontiguousarray(region, dtype=np.float32), sample_rate=MADMOM_SAMPLE_RATE, num_channels=1)
    activations = RNNDownBeatProcessor()(signal)
    # madmom's own default stops at 215, rhythm game songs go a lot faster.
    # num_tempi=None keeps every whole-frame beat interval as a state instead of 60 log-spaced
    # ones. over 60-320 the 60 got coarse enough that a 3/4 click track came out in 4/4
    tracker = DBNDownBeatTrackingProcessor(
        beats_per_bar=list(MADMOM_BEATS_PER_BAR),
        min_bpm=tempo_range.min_bpm,
        max_bpm=tempo_range.max_bpm,
        num_tempi=None,
        fps=MADMOM_FPS,
    )
    beats = tracker(activations)
    if len(beats) == 0:
        return np.zeros(0), np.zeros(0, dtype=np.int64)
    return beats[:, 0] * 1000.0, beats[:, 1].astype(np.int64)


def _track_librosa(region: np.ndarray, sample_rate: int, tempo_range: TempoRange) -> np.ndarray:
    hop = onset_hop(sample_rate)
    env = librosa.onset.onset_strength(y=region, sr=sample_rate, hop_length=hop)
    # the milestone 1 estimate has the octave check, librosa's own guess slips to half tempo on fast songs
    tempo = estimate_tempo(region, sample_rate, 0.0, len(region) / sample_rate * 1000.0, tempo_range)
    _, frames = librosa.beat.beat_track(onset_envelope=env, sr=sample_rate, hop_length=hop, bpm=tempo.bpm, trim=False)
    return np.asarray(librosa.frames_to_time(frames, sr=sample_rate, hop_length=hop) * 1000.0, dtype=np.float64)


def track_beats(
    samples: np.ndarray,
    sample_rate: int,
    start_ms: float,
    end_ms: float,
    tracker: TrackerChoice = "auto",
    tempo_range: TempoRange = TempoRange(),
) -> TrackedBeats:
    if samples.ndim != 1:
        raise ValueError("track_beats expects mono samples")

    use: Tracker
    if tracker == "auto":
        use = "madmom" if madmom_available() and madmom_import_error() is None else "librosa"
    elif tracker == "madmom":
        if not madmom_available():
            raise BeatTrackingError("madmom is not installed, install it with pip install -e .[madmom]")
        error = madmom_import_error()
        if error is not None:
            raise BeatTrackingError(f"madmom is installed but doesn't import ({error})")
        use = "madmom"
    else:
        use = tracker

    region, offset = _region(samples, sample_rate, start_ms, end_ms)
    times = positions = None
    if use == "madmom":
        try:
            times, positions = _track_madmom(region, sample_rate, tempo_range)
        except ImportError as exc:
            # installed but broken, like the pypi 0.16.1 build that wants pkg_resources
            if tracker == "madmom":
                raise BeatTrackingError(f"madmom is installed but doesn't import ({exc})") from exc
            use = "librosa"
    if times is None or positions is None:
        times = _track_librosa(region, sample_rate, tempo_range)
        positions = np.zeros(len(times), dtype=np.int64)

    times = times + offset / sample_rate * 1000.0
    # the padding is silence below the trim threshold, a beat out there is the tracker guessing
    keep = (times >= start_ms - EDGE_TOLERANCE_MS) & (times <= end_ms)
    times, positions = times[keep], positions[keep]
    if len(times) < MIN_BEATS:
        raise BeatTrackingError(f"found {len(times)} beats between the trim points, need at least {MIN_BEATS}")
    if use == "librosa":
        positions = np.arange(len(times), dtype=np.int64) % FALLBACK_BEATS_PER_BAR + 1

    return TrackedBeats(times_ms=times, positions=positions, tracker=use, downbeats_known=use == "madmom")


def bias_correction_ms(tracker: Tracker) -> float:
    # what gets added to a raw beat before snapping. librosa's late bias (+4 to +12 ms) is left alone,
    # it already sits well inside the snap window
    return -MADMOM_BIAS_MS if tracker == "madmom" else 0.0


def bar_numbers(positions: np.ndarray) -> np.ndarray:
    # each downbeat starts a bar. beats before the first one are a pickup, bar 0 like in a score,
    # which pushes the first downbeat to bar 1. no pickup and the first downbeat is bar 0
    positions = np.asarray(positions)
    downbeat = positions == 1
    if not downbeat.any():
        return np.zeros(len(positions), dtype=np.int64)
    bars = np.cumsum(downbeat) - 1
    pickup = not downbeat[0]
    return (bars + (1 if pickup else 0)).clip(min=0).astype(np.int64)
