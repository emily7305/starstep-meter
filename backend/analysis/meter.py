"""Meter: beats per bar from the downbeats, per tempo segment.

madmom's downbeats are where the bars come from. Their spacing on the segment's grid gives
runs of bars of one length, and a run shorter than min_bars is a stumble of the tracker,
so it goes into the run after it (or before, at the end) and that run's bars carry on.

madmom only knows bars of 3 and 4 beats, and on click tracks its downbeats don't always
follow the accents (a 150 bpm 3/4 track came out in 4/4). So the accents get a say: where
every bar of some other length starts on a beat clearly louder than the rest of that bar,
for at least accent_min_bars bars in a row, those bars win over madmom's. That's only when
the length differs and isn't a multiple of madmom's (a crash every two bars isn't 8/4).
Where the length is the same madmom's phase stays, it's the better judge of beat 1 on music.

Beats in a ratio merged section or an off-beat run follow another pulse, or sit half a beat
off, so their downbeats are left out and the bars before them run on through on the grid.
Bars are counted in beats of the grid, so the denominator is always 4: whether 7 beats of
the grid are 7/4 or 7/8 at twice the bpm is a notation choice, like half or double time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from backend.analysis.bars import EDGE_FRACTION
from backend.analysis.grid_fit import NO_DOWNBEAT_CONFIDENCE_SCALE
from backend.analysis.tempo_map import SegmentFit, TempoMapResult


# madmom's bars are 3 or 4 beats, a 2 beat gap between downbeats is one it got wrong
MIN_BAR_BEATS = 3


@dataclass(frozen=True)
class MeterConfig:
    # runs of fewer bars than this are the tracker stumbling, not a meter of their own
    min_bars: int = 4
    # longest bar the downbeat spacing can give, in beats
    max_bar_beats: int = 9
    # an accent bar starts on a beat at least this much stronger than every other beat in the bar.
    # accented clicks give 1.6 to 1.8, music should rarely hold it for long. tuned on clicks only
    accent_ratio: float = 1.3
    accent_min_bars: int = 4
    accent_min_beats: int = 3
    # the accented beat also has to carry at least this share of the segment's median beat strength.
    # real_a's fade-out had 0.03 against 0.02 for its last 13 beats, which passed the
    # ratio and came out as 3/4 over the last 4 s
    accent_min_level: float = 0.25

    def __post_init__(self) -> None:
        if self.min_bars < 1 or self.accent_min_bars < 1 or self.accent_ratio <= 1 or self.accent_min_level < 0:
            raise ValueError("meter thresholds are out of range")
        if not 2 <= self.accent_min_beats <= self.max_bar_beats:
            raise ValueError("bar lengths are out of range")


@dataclass(frozen=True)
class MeterRun:
    start_ms: float
    end_ms: float
    numerator: int
    denominator: int
    confidence: float


@dataclass(frozen=True)
class MeterResult:
    runs: list[MeterRun]
    # the tempo map with each segment's anchor on beat 1 of its first bar
    tempo: TempoMapResult


@dataclass
class _Run:
    # grid index of its first downbeat, beats per bar, downbeats that landed on it
    start: int
    length: int | None
    last: int
    seen: int = 1
    # starts right after a stretch whose downbeats were left out
    after_gap: bool = False
    accent: bool = False


@dataclass
class _Segment:
    # grid indices [k_lo, k_hi) of one tempo segment, and which of them are left out
    k_lo: int
    k_hi: int
    excluded: np.ndarray

    def crossed(self, a: int, b: int) -> bool:
        lo, hi = max(a, self.k_lo) - self.k_lo, max(min(b, self.k_hi) - self.k_lo, 0)
        return bool(self.excluded[lo:hi].any()) if hi > lo else False


def _left_out(times: np.ndarray, seg: SegmentFit) -> np.ndarray:
    out = np.zeros(len(times), dtype=bool)
    for m in seg.ratio_merges:
        out |= (times >= m.start_ms) & (times < m.end_ms)
    for r in seg.offbeat_runs:
        out |= (times >= r.start_ms) & (times <= r.end_ms)
    return out


def _downbeat_runs(downbeats: list[int], seg: _Segment, max_bar: int) -> list[_Run]:
    runs: list[_Run] = []
    for d in downbeats:
        if not runs:
            runs.append(_Run(d, None, d))
            continue
        r = runs[-1]
        gap = d - r.last
        crossed = seg.crossed(r.last, d)
        if r.length is None and MIN_BAR_BEATS <= gap <= max_bar and not crossed:
            r.length, r.last, r.seen = gap, d, r.seen + 1
        elif r.length is not None and gap % r.length == 0:
            # missed downbeats in between, or bars that ran on through a left out stretch
            r.last, r.seen = d, r.seen + 1
        else:
            runs.append(_Run(d, None, d, after_gap=crossed))
    # the downbeat where the bar length changes ends a bar of the old length and starts one of the
    # new, the spacing after it says which. a run whose first bar is already the new length starts
    # on the downbeat before it, where a chart puts the change
    for prev, r in zip(runs, runs[1:]):
        if r.length is not None and prev.length != r.length and r.start - prev.last == r.length and prev.last > prev.start:
            r.start = prev.last
    return runs


def _accent_runs(acc: np.ndarray, k_lo: int, config: MeterConfig) -> list[_Run]:
    """Runs of bars whose first beat is clearly the loudest, for every bar length and phase."""
    found: list[_Run] = []
    n = len(acc)
    finite = acc[np.isfinite(acc)]
    floor = config.accent_min_level * float(np.median(finite)) if len(finite) else np.inf
    for length in range(config.accent_min_beats, config.max_bar_beats + 1):
        for phase in range(length):
            starts = np.arange(phase, n - length + 1, length)
            if len(starts) == 0:
                continue
            ok = np.zeros(len(starts), dtype=bool)
            for i, s in enumerate(starts):
                bar = acc[s:s + length]
                if np.all(np.isfinite(bar)) and bar[0] > floor and bar[0] >= config.accent_ratio * bar[1:].max():
                    ok[i] = True
            i = 0
            while i < len(ok):
                if not ok[i]:
                    i += 1
                    continue
                j = i
                while j < len(ok) and ok[j]:
                    j += 1
                if j - i >= config.accent_min_bars:
                    first = k_lo + int(starts[i])
                    found.append(_Run(first, length, first + (j - i - 1) * length, seen=j - i, accent=True))
                i = j
    # the first bar of a new length also reads as one more bar of the old one: its first beat is
    # the loud one and the beats after it are quiet. it belongs to the new run, otherwise whichever
    # run is longer takes it and the change comes out a bar late (a 4/4 -> 7/4 click track did)
    for r in found:
        assert r.length is not None
        if r.last > r.start and any(o.length != r.length and o.start == r.last and o.last > o.start for o in found):
            r.last -= r.length
            r.seen -= 1
    # the longest stretches first, later ones lose the bars they share with them
    found.sort(key=lambda r: -(r.last - r.start + r.length))
    taken: list[tuple[int, int]] = []
    out: list[_Run] = []
    for r in found:
        assert r.length is not None
        bars = [b for b in range(r.start, r.last + 1, r.length) if not any(a <= b < z or a < b + r.length <= z for a, z in taken)]
        # the longest unbroken piece that's left
        best: list[int] = []
        cur: list[int] = []
        for b in bars:
            cur = cur + [b] if cur and b == cur[-1] + r.length else [b]
            if len(cur) > len(best):
                best = cur
        if len(best) >= config.accent_min_bars:
            out.append(_Run(best[0], r.length, best[-1], seen=len(best), accent=True))
            taken.append((best[0], best[-1] + r.length))
    return out


def _length_over(runs: list[_Run], a: int, b: int, k_hi: int) -> int | None:
    # the bar length madmom's runs give over [a, b), by most beats covered
    cover: dict[int, int] = {}
    for i, r in enumerate(runs):
        if r.length is None:
            continue
        end = runs[i + 1].start if i + 1 < len(runs) else k_hi
        overlap = min(end, b) - max(r.start, a)
        if overlap > 0:
            cover[r.length] = cover.get(r.length, 0) + overlap
    return max(cover, key=lambda length: cover[length]) if cover else None


def _merge_short(runs: list[_Run], seg: _Segment, min_bars: int, default: int) -> list[_Run]:
    runs = list(runs)
    for r in runs:
        if r.length is None:
            r.length = default

    def bars(i: int) -> float:
        end = runs[i + 1].start if i + 1 < len(runs) else seg.k_hi
        return (end - runs[i].start) / runs[i].length

    while len(runs) > 1:
        short = [i for i in range(len(runs)) if bars(i) < min_bars and not runs[i].accent]
        if not short:
            break
        # the shortest first, it's the likeliest stumble. it goes into the run after it, which
        # carries its own bars back over it as far as they fit, and the run before gets what's
        # left. that way the odd bar lands where the downbeats moved, not at a guessed place
        i = min(short, key=bars)
        if i + 1 < len(runs):
            nxt = runs[i + 1]
            assert nxt.length is not None
            nxt.seen += runs[i].seen
            nxt.start -= ((nxt.start - runs[i].start) // nxt.length) * nxt.length
            runs.pop(i)
        else:
            runs[i - 1].seen += runs[i].seen
            runs.pop(i)
    # neighbours with the same bar length on the same lattice are one run. after a left out
    # stretch the lattice from before carries on, the downbeats right after one aren't trusted
    out: list[_Run] = []
    for r in runs:
        prev = out[-1] if out else None
        if prev is not None and prev.length == r.length and ((r.start - prev.start) % r.length == 0 or r.after_gap):
            prev.seen += r.seen
            prev.last = max(prev.last, r.last)
            continue
        out.append(r)
    return out


def _music_start_shift(first: _Run, k_music: int, stop: int, acc: np.ndarray, k_lo: int, config: MeterConfig) -> int:
    """Beats the first run's bars move so the beat the music starts on is beat 1, 0 to leave them.

    madmom can take the first beat of a song for a pickup and put beat 1 a beat later (real_d,
    where the intro opens on the downbeat). A real pickup leads into a downbeat that's louder than
    it, so the bars only move when the first beat is clearly louder than the downbeat the tracker
    picked, and the downbeats they'd get over the run aren't clearly weaker than the tracker's.
    """
    assert first.length is not None
    length = first.length
    downbeat = first.start - ((first.start - k_music) // length) * length
    if downbeat == k_music or first.accent:
        return 0
    lo, hi = k_music - k_lo, min(stop, k_lo + len(acc)) - k_lo
    if lo < 0 or downbeat - k_lo >= hi:
        return 0
    at_music, at_downbeat = acc[lo], acc[downbeat - k_lo]
    if not (np.isfinite(at_music) and np.isfinite(at_downbeat)) or at_music < config.accent_ratio * at_downbeat:
        return 0
    moved, tracked = acc[lo:hi:length], acc[downbeat - k_lo:hi:length]
    if np.isfinite(moved).any() and np.isfinite(tracked).any():
        if np.nanmedian(tracked) >= config.accent_ratio * np.nanmedian(moved):
            return 0
    return k_music - downbeat


def infer_meter(
    tempo: TempoMapResult,
    times_ms: np.ndarray,
    is_downbeat: np.ndarray,
    accents: Callable[[np.ndarray], np.ndarray] | None = None,
    config: MeterConfig = MeterConfig(),
) -> MeterResult:
    """Meter runs over the whole tempo map, contiguous from its first start to its last end.

    accents(times_ms) gives how strong the attack is at each grid line, None for beats only.
    The returned tempo map has each segment's anchor moved by whole beats onto beat 1 where
    the accents put beat 1 somewhere else than madmom did. No grid line moves.
    """
    times = np.asarray(times_ms, dtype=np.float64)
    downbeat = np.asarray(is_downbeat, dtype=bool)
    scale = 1.0 if tempo.downbeats_known else NO_DOWNBEAT_CONFIDENCE_SCALE
    segments = list(tempo.segments)
    indices = tempo.indices.copy()
    pieces: list[tuple[float, int, float]] = []
    for si, s in enumerate(segments):
        period, anchor = s.fit.period_ms, s.fit.offset_ms
        k_lo = int(np.ceil((s.start_ms - anchor) / period - EDGE_FRACTION))
        k_hi = max(k_lo + 1, int(np.ceil((s.end_ms - anchor) / period - EDGE_FRACTION)))
        grid = anchor + period * np.arange(k_lo, k_hi)
        seg = _Segment(k_lo, k_hi, _left_out(grid, s))
        t = times[s.first:s.stop]
        k = s.fit.indices
        keep = ~_left_out(t, s)
        downbeats = sorted({int(x) for x in k[keep & downbeat[s.first:s.stop]] if k_lo <= x < k_hi})
        runs = _downbeat_runs(downbeats, seg, config.max_bar_beats)

        acc = None
        if accents is not None and len(grid) >= config.accent_min_bars * config.accent_min_beats:
            acc = np.asarray(accents(grid), dtype=np.float64).copy()
            acc[seg.excluded] = np.nan
            winners: list[_Run] = []
            for ar in _accent_runs(acc, k_lo, config):
                assert ar.length is not None
                tracked = _length_over(runs, ar.start, ar.last + ar.length, k_hi)
                if tracked is None or (ar.length != tracked and ar.length % tracked != 0):
                    winners.append(ar)
            if winners:
                # the accent bars take over where they are, madmom's downbeats fill in around them
                winners.sort(key=lambda r: r.start)
                runs = []
                cursor = k_lo
                for ar in winners:
                    assert ar.length is not None
                    runs += _downbeat_runs([d for d in downbeats if cursor <= d < ar.start], seg, config.max_bar_beats)
                    runs.append(ar)
                    cursor = ar.last + ar.length
                runs += _downbeat_runs([d for d in downbeats if d >= cursor], seg, config.max_bar_beats)

        default = 4
        runs = _merge_short(runs, seg, config.min_bars, default) if runs else [_Run(k_lo, default, k_lo, seen=0)]
        # the song's own start, when the tracker heard a beat right there. the seen count stays, it's
        # about how well the bar length holds and that didn't change
        if si == 0 and acc is not None and len(k) and int(k[0]) <= k_lo:
            stop = runs[1].start if len(runs) > 1 else k_hi
            runs[0].start += _music_start_shift(runs[0], int(k[0]), stop, acc, k_lo, config)

        # the anchor goes onto beat 1 of the first run, its first downbeat from the first tracked beat on.
        # that's madmom's first downbeat already unless the accents or a stumble said otherwise
        first = runs[0]
        assert first.length is not None
        k_first = int(k[0]) if len(k) else k_lo
        shift = first.start - ((first.start - k_first) // first.length) * first.length
        if shift:
            fit = s.fit
            moved = type(fit)(
                period_ms=fit.period_ms,
                offset_ms=fit.offset_ms + shift * fit.period_ms,
                indices=fit.indices - shift,
                residuals_ms=fit.residuals_ms,
                inliers=fit.inliers,
                residual_rms_ms=fit.residual_rms_ms,
                confidence=fit.confidence,
            )
            segments[si] = type(s)(s.first, s.stop, s.start_ms, s.end_ms, moved, s.ratio_merges, s.offbeat_runs, s.half_shifted)
            indices[s.first:s.stop] = moved.indices

        for i, r in enumerate(runs):
            assert r.length is not None
            end = runs[i + 1].start if i + 1 < len(runs) else k_hi
            bars = max(1.0, (end - r.start) / r.length)
            start_ms = s.start_ms if i == 0 else anchor + period * r.start
            pieces.append((start_ms, r.length, min(1.0, r.seen / bars) * scale))

    runs_out: list[MeterRun] = []
    end_ms = segments[-1].end_ms if segments else 0.0
    for i, (start_ms, length, conf) in enumerate(pieces):
        stop = pieces[i + 1][0] if i + 1 < len(pieces) else end_ms
        prev = runs_out[-1] if runs_out else None
        # the same meter either side of a tempo change is one meter segment, the tempo
        # segment's anchor restarts the bars there anyway
        starts_segment = any(abs(start_ms - s.start_ms) < 1e-6 for s in segments)
        if prev is not None and prev.numerator == length and starts_segment:
            span_prev, span = prev.end_ms - prev.start_ms, stop - start_ms
            joined_conf = (prev.confidence * span_prev + conf * span) / max(span_prev + span, 1e-9)
            runs_out[-1] = MeterRun(prev.start_ms, stop, length, 4, joined_conf)
            continue
        runs_out.append(MeterRun(start_ms, stop, length, 4, conf))
    moved_tempo = TempoMapResult(
        segments=segments,
        residuals_ms=tempo.residuals_ms,
        indices=indices,
        segment_of_beat=tempo.segment_of_beat,
        inliers=tempo.inliers,
        downbeats_known=tempo.downbeats_known,
    )
    return MeterResult(runs=runs_out, tempo=moved_tempo)
