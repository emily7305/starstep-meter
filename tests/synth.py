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
    # (beat index, beats per bar) pairs. that beat is a downbeat and bars from it on have the new length
    meter_changes: tuple[tuple[int, int], ...] = ()
    # clicks before the first downbeat
    pickup_beats: int = 0
    # (beat index, bpm) pairs. that beat is the first one of the new tempo, the gap
    # before it still belongs to the old one
    tempo_changes: tuple[tuple[int, float], ...] = ()
    # gaussian jitter on every onset after the first, in ms. 0 is a perfect grid
    jitter_ms: float = 0.0
    # (first beat, beat count, ms) sections where every onset moves by a uniform random amount up
    # to ms either way, a stretch played badly on purpose
    messy: tuple[tuple[int, int, float], ...] = ()
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
    for k, (first, count, ms) in enumerate(spec.messy):
        rng = np.random.default_rng([spec.seed, 2, k])
        times[first:first + count] += rng.uniform(-ms / 1000.0, ms / 1000.0, count)
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


def downbeat_indices(spec: ClickTrackSpec) -> np.ndarray:
    """Beat indices that start a bar, with the bar length changing at each meter change."""
    changes = dict(spec.meter_changes)
    out = []
    k, length = spec.pickup_beats, spec.beats_per_bar
    while k < spec.beats:
        out.append(k)
        nxt = k + length
        # a change before the next regular downbeat cuts the bar short there
        for at in sorted(changes):
            if k < at <= nxt:
                nxt, length = at, changes[at]
                break
        k = nxt
    return np.array(out, dtype=np.int64)


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
    is_downbeat = whole & np.isin(np.round(positions).astype(np.int64), downbeat_indices(spec))
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


# --- drum patterns, for the half and double time feel checks ---

Feel = str


@dataclass(frozen=True)
class DrumTrackSpec:
    # the steady pulse, every feel below is written against it
    bpm: float = 130.0
    # 4 beat bars of that pulse
    bars: int = 48
    lead_silence_s: float = 0.5
    tail_silence_s: float = 1.0
    sample_rate: int = 44100
    # (first bar, bar count, feel) with feel "half" or "double". everything else is the plain
    # backbeat: kick on beats 1 and 3, snare on 2 and 4
    sections: tuple[tuple[int, int, Feel], ...] = ()
    # hats on every half beat all the way through, louder on the beat. with them even, madmom
    # followed the double time section to twice the tempo and stayed there
    hat_level: float = 0.4
    offbeat_hat_level: float = 0.12
    seed: int = 0

    def cache_name(self) -> str:
        key = repr(sorted(asdict(self).items())) + _SOURCE_HASH
        digest = hashlib.sha256(key.encode()).hexdigest()[:12]
        return f"drums-{self.bpm:g}bpm-{digest}.wav"


@dataclass
class DrumTrack:
    spec: DrumTrackSpec
    samples: np.ndarray
    # ground truth in ms from the first sample
    beat_ms: float
    first_beat_ms: float
    # (start_ms, end_ms, feel) of each section, on the bar lines of the pulse
    sections_ms: list[tuple[float, float, Feel]]
    duration_ms: float
    sample_rate: int = field(init=False)

    def __post_init__(self) -> None:
        self.sample_rate = self.spec.sample_rate

    def bar_ms(self, bar: int) -> float:
        return self.first_beat_ms + 4 * bar * self.beat_ms


# (kicks, snares) per 4 beat bar of the pulse, in beats. half time has one kick and the snare on
# beat 3, double time a kick on every beat and the snare on every off-beat
_PATTERNS: dict[Feel, tuple[tuple[float, ...], tuple[float, ...]]] = {
    "plain": ((0.0, 2.0), (1.0, 3.0)),
    "half": ((0.0,), (2.0,)),
    "double": ((0.0, 1.0, 2.0, 3.0), (0.5, 1.5, 2.5, 3.5)),
}


def _decay(sample_rate: int, length_ms: float, decay_ms: float) -> tuple[np.ndarray, np.ndarray]:
    n = int(round(length_ms / 1000.0 * sample_rate))
    t = np.arange(n) / sample_rate
    return t, np.exp(-t / (decay_ms / 1000.0))


def _kick(sample_rate: int) -> np.ndarray:
    # a sweep from 120 down to 50 hz, all of it under the 150 hz band edge
    t, env = _decay(sample_rate, 250.0, 70.0)
    freq = 50.0 + 70.0 * np.exp(-t / 0.03)
    phase = 2.0 * np.pi * np.cumsum(freq) / sample_rate
    return 0.9 * np.sin(phase) * env


def _filtered_noise(rng: np.random.Generator, n: int, sample_rate: int, lo_hz: float, hi_hz: float) -> np.ndarray:
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    spectrum[(freqs < lo_hz) | (freqs > hi_hz)] = 0.0
    noise = np.fft.irfft(spectrum, n)
    return noise / (np.abs(noise).max() + 1e-12)


def _snare(sample_rate: int, rng: np.random.Generator) -> np.ndarray:
    t, env = _decay(sample_rate, 180.0, 45.0)
    body = 0.35 * np.sin(2.0 * np.pi * 190.0 * t) * env
    return body + 0.45 * _filtered_noise(rng, len(t), sample_rate, 300.0, 9000.0) * env


def _hat(sample_rate: int, rng: np.random.Generator, level: float) -> np.ndarray:
    t, env = _decay(sample_rate, 60.0, 12.0)
    return level * _filtered_noise(rng, len(t), sample_rate, 7000.0, 15000.0) * env


def drum_feels(spec: DrumTrackSpec) -> list[Feel]:
    feels = ["plain"] * spec.bars
    for first, count, feel in spec.sections:
        if feel not in _PATTERNS:
            raise ValueError(f"unknown feel {feel}")
        for bar in range(first, min(first + count, spec.bars)):
            feels[bar] = feel
    return feels


def drum_track(spec: DrumTrackSpec = DrumTrackSpec()) -> DrumTrack:
    sr = spec.sample_rate
    rng = np.random.default_rng(spec.seed)
    beat_s = 60.0 / spec.bpm
    kick, snare, hat = _kick(sr), _snare(sr, rng), _hat(sr, rng, 1.0)
    total = int(round((spec.lead_silence_s + spec.bars * 4 * beat_s + 0.3 + spec.tail_silence_s) * sr))
    audio = np.zeros(total)

    def put(wave: np.ndarray, beat: float) -> None:
        start = int(round((spec.lead_silence_s + beat * beat_s) * sr))
        stop = min(total, start + len(wave))
        audio[start:stop] += wave[: stop - start]

    for bar, feel in enumerate(drum_feels(spec)):
        kicks, snares = _PATTERNS[feel]
        for b in kicks:
            put(kick, 4 * bar + b)
        for b in snares:
            put(snare, 4 * bar + b)
        for half in range(8):
            put(hat * (spec.offbeat_hat_level if half % 2 else spec.hat_level), 4 * bar + half / 2.0)
    first_ms = round(spec.lead_silence_s * sr) / sr * 1000.0
    beat_ms = beat_s * 1000.0
    sections = [
        (first_ms + 4 * first * beat_ms, first_ms + 4 * min(first + count, spec.bars) * beat_ms, feel)
        for first, count, feel in spec.sections
    ]
    return DrumTrack(
        spec=spec,
        samples=(audio * 0.6).astype(np.float32),
        beat_ms=beat_ms,
        first_beat_ms=first_ms,
        sections_ms=sections,
        duration_ms=total / sr * 1000.0,
    )


def cached_drum_wav(spec: DrumTrackSpec = DrumTrackSpec(), fixtures_dir: Path = FIXTURES_DIR) -> tuple[Path, DrumTrack]:
    track = drum_track(spec)
    path = fixtures_dir / spec.cache_name()
    if not path.exists():
        tmp = path.with_name(f".{path.stem}.{os.getpid()}.tmp.wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(tmp, track.samples, spec.sample_rate, subtype="FLOAT")
        os.replace(tmp, path)
    return path, track
