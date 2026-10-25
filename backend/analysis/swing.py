"""Swing and gallop: stretches where the notes between the beats are uneven.

This reads where the onsets sit between the lines of the grid the tempo map already has, and
never moves a beat or changes a bpm. Each beat's onset envelope is sampled at `steps` points
from its line to the next, the samples are averaged over a few bars, and the averaged profile
says which positions inside the beat have notes:

- swing: one note late in the beat, around 2/3 for a 2:1 swing, and nothing on the half
- gallop: 8th-16th-16th, notes on the half and three quarters and nothing on the quarter
- reverse gallop: 16th-16th-8th, notes on the quarter and the half and nothing on three quarters
- the same two gallops on a triplet base, at 2/3 and 5/6, or 1/6 and 1/3

Straight 8ths, straight 16ths and plain triplets aren't reported, a chart's usual divisions
already hold them. Each section says which division a chart editor needs for its notes: 1/12
for swing, 1/16 for a straight gallop, 1/24 for a triplet one, counted in beats of the grid
it was read on. These are suggestions only, nothing applies them.

The envelope is a log-compressed spectral flux with a short window, so quiet hats count next
to a loud kick. Positions are measured against the beat's own onset in the same profile, so a
constant lag of the envelope cancels out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

from backend.analysis.bars import EDGE_FRACTION, regions

Kind = Literal["swing", "gallop", "reverse_gallop"]

# 512 samples is 11.6 ms at 44.1 khz, short enough that a 16th at 300 bpm is two windows away.
# the hop is a quarter of a 48th of a beat at 300 bpm
FFT_AT_44K = 512
HOP_AT_44K = 64
_CHUNK_FRAMES = 4096


@dataclass(frozen=True)
class SwingConfig:
    # samples per beat in a profile
    steps: int = 48
    # bars averaged for each bar's call, centred on it
    window_bars: int = 3
    # a run shorter than this isn't a section a chart would set a division for
    min_bars: int = 2
    # a position has a note when its peak over the profile's floor reaches present of the beat's
    # own, and is empty under absent. tuned on clicks and generated envelopes, revisit on songs
    present: float = 0.4
    absent: float = 0.2
    # how far from its position a note can sit and still count, in beats
    tolerance: float = 1.0 / 24.0
    # where a swung 8th's second note has to sit. 2:1 is 0.667, 3:2 (0.6) is too light for a
    # triplet division and 3:1 (0.75) is a dotted 8th on the 16th grid
    swing_from: float = 0.62
    swing_to: float = 0.71
    # beats whose envelope peaks under this share of the median beat's are too quiet to read
    quiet: float = 0.2

    def __post_init__(self) -> None:
        if not 0 < self.absent < self.present:
            raise ValueError("swing thresholds are out of range")
        if self.window_bars < 1 or self.min_bars < 1 or self.steps < 24:
            raise ValueError("swing window, length or resolution is out of range")


@dataclass(frozen=True)
class Envelope:
    times_ms: np.ndarray
    values: np.ndarray


@dataclass(frozen=True)
class SwingSection:
    start_ms: float
    end_ms: float
    kind: Kind
    # long note over short note: 2.0 for a 2:1 swing and a straight gallop, 4.0 for a triplet gallop
    ratio: float
    score: float
    # notes per 4/4 measure at grid_bpm, 12 is a chart editor's 1/12
    division: int
    grid_bpm: float


@dataclass(frozen=True)
class _Call:
    kind: Kind
    ratio: float
    score: float
    division: int


def envelope(samples: np.ndarray, sample_rate: int, start_ms: float, end_ms: float) -> Envelope:
    """Log-compressed positive spectral flux over [start_ms, end_ms], all bins together."""
    if samples.ndim != 1:
        raise ValueError("envelope expects mono samples")
    scale = sample_rate / 44100.0
    n_fft = int(2 ** round(np.log2(FFT_AT_44K * scale)))
    hop = max(1, int(round(HOP_AT_44K * scale)))
    lo = max(0, int(start_ms / 1000.0 * sample_rate) - n_fft)
    hi = min(len(samples), int(np.ceil(end_ms / 1000.0 * sample_rate)) + n_fft)
    seg = np.asarray(samples[lo:hi], dtype=np.float32)
    peak = float(np.max(np.abs(seg))) if len(seg) else 0.0
    if peak > 0:
        # the log's knee should sit at the same place on a quiet master and a loud one
        seg = seg / peak
    if len(seg) < n_fft:
        seg = np.pad(seg, (0, n_fft - len(seg)))
    window = np.hanning(n_fft + 2)[1:-1].astype(np.float32)
    frames = 1 + (len(seg) - n_fft) // hop
    out = np.zeros(frames)
    prev: np.ndarray | None = None
    for a in range(0, frames, _CHUNK_FRAMES):
        b = min(frames, a + _CHUNK_FRAMES)
        idx = np.arange(n_fft)[None, :] + hop * np.arange(a, b)[:, None]
        mag = np.log1p(np.abs(np.fft.rfft(seg[idx] * window, axis=1)))
        stacked = mag if prev is None else np.vstack((prev[None, :], mag))
        rise = np.maximum(0.0, np.diff(stacked, axis=0)).sum(axis=1)
        out[a:b] = rise if prev is not None else np.concatenate(([0.0], rise))
        prev = mag[-1]
    times = (lo + hop * np.arange(frames) + n_fft / 2.0) / sample_rate * 1000.0
    return Envelope(times_ms=times, values=out)


def _positions(config: SwingConfig) -> np.ndarray:
    # a quarter of a beat before the line too, so the beat's own onset is read from both sides
    first = -config.steps // 4
    return np.arange(first, config.steps) / config.steps


def _raw_rows(env: Envelope, lines_ms: np.ndarray, config: SwingConfig) -> np.ndarray:
    lines = np.asarray(lines_ms, dtype=np.float64)
    if len(lines) < 2 or len(env.times_ms) == 0:
        return np.zeros((0, len(_positions(config))))
    start, length = lines[:-1], np.diff(lines)
    # the mean over each step's whole width, not the value at its centre. a click's flux is a
    # spike a few frames wide, and a point every 8.6 ms (48 steps at 146 bpm) can step over it
    half = 0.5 / config.steps
    lo = start[:, None] + (_positions(config)[None, :] - half) * length[:, None]
    hi = start[:, None] + (_positions(config)[None, :] + half) * length[:, None]
    total = np.cumsum(env.values)
    below = np.interp(lo.ravel(), env.times_ms, total, left=0.0, right=total[-1])
    above = np.interp(hi.ravel(), env.times_ms, total, left=0.0, right=total[-1])
    return ((above - below) / np.maximum((hi - lo).ravel(), 1e-9)).reshape(lo.shape)


def beat_profiles(
    env: Envelope, lines_ms: np.ndarray, config: SwingConfig = SwingConfig(), reference: float | None = None
) -> np.ndarray:
    """One row per beat between consecutive lines, the envelope at _positions of that beat.

    Each row is divided by its own peak, so a loud bar doesn't outvote a quiet one. A beat
    whose peak is under `quiet` of the reference (the median beat's peak, these beats' own
    when it isn't given) is too quiet to read and comes back as a row of nan.
    """
    rows = _raw_rows(env, lines_ms, config)
    peaks = rows.max(axis=1) if len(rows) else np.zeros(0)
    if reference is None:
        reference = float(np.median(peaks[peaks > 0])) if np.any(peaks > 0) else 0.0
    out = np.full(rows.shape, np.nan)
    ok = (peaks > 0) & (peaks >= config.quiet * reference)
    out[ok] = rows[ok] / peaks[ok, None]
    return out


def _peak(profile: np.ndarray, xs: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    """Where the profile peaks inside [lo, hi] and its value, with a parabola through the top three."""
    inside = np.flatnonzero((xs >= lo - 1e-9) & (xs <= hi + 1e-9))
    if len(inside) == 0:
        return (lo + hi) / 2.0, 0.0
    i = int(inside[np.argmax(profile[inside])])
    value = float(profile[i])
    if 0 < i < len(profile) - 1:
        a, b, c = profile[i - 1], profile[i], profile[i + 1]
        den = a - 2 * b + c
        if den < 0:
            shift = 0.5 * (a - c) / den
            step = xs[1] - xs[0]
            return float(xs[i] + shift * step), float(b - 0.25 * (a - c) * shift)
    return float(xs[i]), value


def classify(profile: np.ndarray, config: SwingConfig = SwingConfig()) -> _Call | None:
    """Swing or gallop for one averaged beat profile, None when it's straight or unclear."""
    if not np.all(np.isfinite(profile)):
        return None
    xs = _positions(config)
    tol = config.tolerance
    floor = float(np.percentile(profile, 20))
    _, on_beat = _peak(profile, xs, -tol, tol)
    span = on_beat - floor
    if span <= 0:
        return None

    def note(x: float) -> float:
        return (_peak(profile, xs, x - tol, x + tol)[1] - floor) / span

    def where(x: float) -> float:
        return _peak(profile, xs, x - tol, x + tol)[0]

    half, quarter, three_q = note(1 / 2), note(1 / 4), note(3 / 4)
    third, two_thirds = note(1 / 3), note(2 / 3)
    sixth, five_sixths = note(1 / 6), note(5 / 6)
    has, empty = config.present, config.absent

    if half >= has and three_q >= has and quarter < empty and third < empty:
        a, b = where(1 / 2), where(3 / 4)
        return _Call("gallop", a / (b - a), min(half, three_q, 1.0) - max(quarter, third), 16)
    if quarter >= has and half >= has and three_q < empty and two_thirds < empty:
        a, b = where(1 / 4), where(1 / 2)
        return _Call("reverse_gallop", (1.0 - b) / a, min(quarter, half, 1.0) - max(three_q, two_thirds), 16)
    if two_thirds >= has and five_sixths >= has and third < empty and half < empty:
        a, b = where(2 / 3), where(5 / 6)
        return _Call("gallop", a / (b - a), min(two_thirds, five_sixths, 1.0) - max(third, half), 24)
    if sixth >= has and third >= has and two_thirds < empty and half < empty:
        a, b = where(1 / 6), where(1 / 3)
        return _Call("reverse_gallop", (1.0 - b) / a, min(sixth, third, 1.0) - max(two_thirds, half), 24)
    # after the gallops, a triplet gallop has the same late note plus one at 5/6. the late note is
    # searched for over a wide span, a 2:1 swing at 300 bpm reads about 0.65
    at, late = _peak(profile, xs, 0.55, 0.78)
    late = (late - floor) / span
    others = max(half, quarter, third, five_sixths)
    if config.swing_from <= at <= config.swing_to and late >= has and others < empty:
        return _Call("swing", at / (1.0 - at), min(1.0, late) - others, 12)
    return None


@dataclass
class _Bars:
    tempo: int
    starts_ms: np.ndarray
    ends_ms: np.ndarray
    # (bars, positions), each bar's beats averaged, nan where none could be read
    profiles: np.ndarray


def _bar_lines(segments: Sequence, meter: Sequence) -> list[tuple[int, list[tuple[float, float, np.ndarray]]]]:
    """Per region, each bar as (start, end, its grid lines from its first beat to the line after its last)."""
    out = []
    for r in regions(segments, meter):
        s = segments[r.tempo]
        lo = max(r.from_ms, s.start_ms - EDGE_FRACTION * r.period_ms)
        hi = min(r.stop_ms, s.end_ms)
        k = int(np.ceil((lo - r.ref_ms) / r.bar_ms - 1e-9))
        bars = []
        while r.ref_ms + k * r.bar_ms < hi - EDGE_FRACTION * r.period_ms:
            a = r.ref_ms + k * r.bar_ms
            b = a + r.bar_ms
            k += 1
            first = np.ceil((a - s.anchor_ms) / r.period_ms - 1e-6)
            last = np.floor((b - s.anchor_ms) / r.period_ms + 1e-6)
            bars.append((a, min(b, s.end_ms), s.anchor_ms + r.period_ms * np.arange(first, last + 1)))
        if bars:
            out.append((r.tempo, bars))
    return out


def _bars(segments: Sequence, meter: Sequence, env: Envelope, config: SwingConfig) -> list[_Bars]:
    laid_out = _bar_lines(segments, meter)
    # quiet is against the whole song's beats, a quiet song section shouldn't read as normal
    peaks = [_raw_rows(env, lines, config).max(axis=1) for _, bars in laid_out for _, _, lines in bars if len(lines) >= 2]
    every = np.concatenate(peaks) if peaks else np.zeros(0)
    reference = float(np.median(every[every > 0])) if np.any(every > 0) else 0.0
    out: list[_Bars] = []
    width = len(_positions(config))
    for tempo, bars in laid_out:
        s = segments[tempo]
        profiles = []
        for a, b, lines in bars:
            felt = any(fa < b and fb > a for fa, fb in s.felt)
            rows = beat_profiles(env, lines, config, reference) if len(lines) >= 2 and not felt else np.zeros((0, width))
            good = rows[np.all(np.isfinite(rows), axis=1)]
            profiles.append(good.mean(axis=0) if len(good) else np.full(width, np.nan))
        out.append(_Bars(tempo, np.array([a for a, _, _ in bars]), np.array([b for _, b, _ in bars]), np.array(profiles)))
    return out


def _same(a: _Call | None, b: _Call | None) -> bool:
    return a is not None and b is not None and a.kind == b.kind and a.division == b.division


def _window(profiles: np.ndarray, i: int, half: int) -> np.ndarray:
    part = profiles[max(0, i - half):i + half + 1]
    good = part[np.all(np.isfinite(part), axis=1)]
    return good.mean(axis=0) if len(good) else np.full(profiles.shape[1], np.nan)


def find_sections(
    segments: Sequence,
    meter: Sequence,
    env: Envelope,
    config: SwingConfig = SwingConfig(),
) -> list[SwingSection]:
    """Swing and gallop sections over the whole tempo map, on bar lines.

    segments are notation.Segment (start_ms, end_ms, bpm, anchor_ms, felt), meter the meter
    runs or the report's meter map. A bar that touches a felt section is left out, its notes
    follow another pulse.
    """
    out: list[SwingSection] = []
    for bars in _bars(segments, meter, env, config):
        n = len(bars.starts_ms)
        half = config.window_bars // 2
        windowed = [classify(_window(bars.profiles, i, half), config) for i in range(n)]
        single = [classify(bars.profiles[i], config) for i in range(n)]
        # a bar goes by its window, or by itself when a bar next to it reads the same on its own.
        # a 3 bar window drowns a section only 2 bars long
        called = list(windowed)
        for i in range(n):
            if called[i] is None and any(_same(single[i], single[j]) for j in (i - 1, i + 1) if 0 <= j < n):
                called[i] = single[i]
        i = 0
        while i < n:
            call = called[i]
            if call is None:
                i += 1
                continue
            j = i
            while j < n and _same(called[j], call):
                j += 1
            # the window blurs an edge by up to half its length, the bars on their own decide it
            a, z = i, j
            while a < z and not _same(single[a], call):
                a += 1
            while z > a and not _same(single[z - 1], call):
                z -= 1
            while a > 0 and _same(single[a - 1], call):
                a -= 1
            while z < n and _same(single[z], call):
                z += 1
            if z - a >= config.min_bars:
                calls = [c for c in called[a:z] + single[a:z] if _same(c, call)]
                ratio = float(np.median([c.ratio for c in calls]))
                score = float(np.clip(np.mean([c.score for c in calls]), 0.0, 1.0))
                start = max(segments[bars.tempo].start_ms, float(bars.starts_ms[a]))
                out.append(SwingSection(start, float(bars.ends_ms[z - 1]), call.kind, ratio, score, call.division, segments[bars.tempo].bpm))
            i = max(j, z)
    return sorted(out, key=lambda s: s.start_ms)
