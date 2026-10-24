"""Synthetic test audio with known ground truth.

Everything here is generated in code. Generated WAVs are cached under
tests/fixtures/ (git-ignored) and the cache key includes a hash of this
file, so editing the generator regenerates them.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_SOURCE_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class ClickTrackSpec:
    bpm: float = 120.0
    beats: int = 40
    lead_silence_s: float = 2.0
    tail_silence_s: float = 2.0
    sample_rate: int = 44100
    click_freq_hz: float = 1000.0
    # 30 ms with a 5 ms decay ends around -52 db, so the hard cut at the end is basically inaudible
    click_ms: float = 30.0
    click_decay_ms: float = 5.0
    amplitude: float = 0.5
    # white noise rms in dbfs over the whole file, None = digital silence
    noise_floor_db: float | None = None
    # louder, higher click on beat 1 of each bar, the downbeat tracker needs it to find beat 1
    accent_downbeats: bool = False
    beats_per_bar: int = 4
    # clicks before the first downbeat
    pickup_beats: int = 0
    # (beat index, bpm) pairs. that beat is the first one of the new tempo, the gap
    # before it still belongs to the old one
    tempo_changes: tuple[tuple[int, float], ...] = ()
    # gaussian jitter on every onset after the first, in ms. 0 is a perfect grid
    jitter_ms: float = 0.0
    # plain click halfway between beats at this fraction of amplitude, like eighth note hats
    # 0 means none. it's what makes half or double tempo a real question
    offbeat_level: float = 0.0
    # (first beat, beat count, positions) sections where the clicks follow a rhythm instead of
    # the beat, the tempo underneath stays the same. positions are in beats from each 4 beat
    # bar's start, e.g. (0, 1.5, 3) for a dotted 3-3-2 bar, (0, 4/3, 8/3) for a triplet feel
    patterns: tuple[tuple[int, int, tuple[float, ...]], ...] = ()
    seed: int = 0

    def cache_name(self) -> str:
        key = repr(sorted(asdict(self).items())) + _SOURCE_HASH
        digest = hashlib.sha256(key.encode()).hexdigest()[:12]
        return f"click-{self.bpm:g}bpm-{digest}.wav"


@dataclass
class ClickTrack:
    spec: ClickTrackSpec
    samples: np.ndarray
    # ground truth, all in ms from the first sample
    onsets_ms: np.ndarray
    downbeats_ms: np.ndarray
    content_start_ms: float
    content_end_ms: float
    duration_ms: float
    # onset of the first beat of each new tempo, same order as spec.tempo_changes
    change_ms: np.ndarray
    sample_rate: int = field(init=False)

    def __post_init__(self) -> None:
        self.sample_rate = self.spec.sample_rate


def _click(sample_rate: int, freq_hz: float, length_ms: float, decay_ms: float) -> np.ndarray:
    n = int(round(length_ms / 1000.0 * sample_rate))
    t = np.arange(n) / sample_rate
    return np.sin(2.0 * np.pi * freq_hz * t) * np.exp(-t / (decay_ms / 1000.0))


def beat_times_s(spec: ClickTrackSpec) -> np.ndarray:
    # each gap uses the tempo in force at the beat it starts from
    bpm = np.full(spec.beats, float(spec.bpm))
    for index, new_bpm in sorted(spec.tempo_changes):
        bpm[index:] = new_bpm
    gaps = 60.0 / bpm[:-1]
    times = spec.lead_silence_s + np.concatenate(([0.0], np.cumsum(gaps)))
    if spec.jitter_ms > 0.0:
        # own stream, so adding jitter doesn't change the noise floor of an existing spec
        rng = np.random.default_rng([spec.seed, 1])
        times[1:] += rng.normal(0.0, spec.jitter_ms / 1000.0, spec.beats - 1)
    return times


def click_positions(spec: ClickTrackSpec) -> np.ndarray:
    """Where each click sounds, in beats of the underlying grid, fractional inside patterns."""
    positions = np.arange(spec.beats, dtype=np.float64)
    keep = np.ones(spec.beats, dtype=bool)
    extra: list[float] = []
    for first, count, pattern in spec.patterns:
        keep[first:first + count] = False
        for bar in range(0, count, 4):
            extra.extend(first + bar + p for p in pattern if bar + p < count)
    return np.sort(np.concatenate((positions[keep], extra)))


def click_track(spec: ClickTrackSpec = ClickTrackSpec()) -> ClickTrack:
    sr = spec.sample_rate
    grid_s = beat_times_s(spec)
    positions = click_positions(spec)
    # a click between two beats sits at the same fraction of the gap between them
    times_s = np.interp(positions, np.arange(spec.beats), grid_s)
    # onsets are rounded to whole samples, truth is taken from the rounded index so it's exact
    onset_idx = np.round(times_s * sr).astype(np.int64)

    plain = _click(sr, spec.click_freq_hz, spec.click_ms, spec.click_decay_ms) * spec.amplitude
    accent = _click(sr, spec.click_freq_hz * 1.5, spec.click_ms, spec.click_decay_ms) * min(spec.amplitude * 1.6, 0.95)
    click_len = len(plain)

    content_end_idx = int(onset_idx[-1]) + click_len
    total = content_end_idx + int(round(spec.tail_silence_s * sr))
    audio = np.zeros(total, dtype=np.float64)

    whole = positions == np.round(positions)
    is_downbeat = whole & (((np.round(positions).astype(np.int64) - spec.pickup_beats) % spec.beats_per_bar) == 0)
    for i, start in enumerate(onset_idx):
        wave = accent if (spec.accent_downbeats and is_downbeat[i]) else plain
        audio[start:start + click_len] += wave
    if spec.offbeat_level > 0.0:
        for start in (onset_idx[:-1] + onset_idx[1:]) // 2:
            audio[start:start + click_len] += plain * spec.offbeat_level

    if spec.noise_floor_db is not None:
        rng = np.random.default_rng(spec.seed)
        audio += rng.standard_normal(total) * 10.0 ** (spec.noise_floor_db / 20.0)

    to_ms = 1000.0 / sr
    return ClickTrack(
        spec=spec,
        samples=audio.astype(np.float32),
        onsets_ms=onset_idx * to_ms,
        downbeats_ms=onset_idx[is_downbeat] * to_ms,
        content_start_ms=float(onset_idx[0] * to_ms),
        content_end_ms=content_end_idx * to_ms,
        duration_ms=total * to_ms,
        change_ms=np.array([np.round(grid_s[index] * sr) * to_ms for index, _ in sorted(spec.tempo_changes)]),
    )


def write_wav(track: ClickTrack, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # float wav so the wav-input tests see exactly what was generated
    sf.write(path, track.samples, track.sample_rate, subtype="FLOAT")
    return path


def cached_click_wav(spec: ClickTrackSpec = ClickTrackSpec(), fixtures_dir: Path = FIXTURES_DIR) -> tuple[Path, ClickTrack]:
    track = click_track(spec)
    path = fixtures_dir / spec.cache_name()
    if not path.exists():
        # temp name + rename, two test runs at once could otherwise read a half-written wav
        tmp = path.with_name(f".{path.stem}.{os.getpid()}.tmp.wav")
        write_wav(track, tmp)
        os.replace(tmp, path)
    return path, track
