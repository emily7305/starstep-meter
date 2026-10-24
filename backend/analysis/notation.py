"""Notation suggestions: where a chart may write the same pulse at another tempo.

The audio can't say which way a charter writes a pulse, so these are only suggestions, the
report keeps them and an edit applies or dismisses each one.

Half and double time feel. A plain backbeat has the snare on beats 2 and 4, so the snare
comes round every two beats of the notated tempo. Folding the snare band over four beats of
the grid at half beat steps, a plain bar has two hits half a cycle apart. One hit per cycle
is the backbeat at half the grid's tempo, four (on every beat or every off-beat, nothing in
between) is twice it. A backbeat swaps kick and snare, so half and double also need the kick
band's hits half a backbeat away from the snare's, otherwise it's something else on every
beat (a click track, a ride). Windows of a few bars slide one bar at a time, every bar takes
the class most of its windows gave, and runs of half or double bars become suggestions with
their edges on bar lines. Only 4/4 bars count, and never a bar in a ratio merged section,
those already follow another pulse.

Fold. A first or last stretch near the edge of the song that the tempo map kept at its own
tempo may still be its neighbour's, the tracker losing the beat in an outro. The neighbour's
grid is carried through it, and if the onsets sit on that grid at least as well as on the
stretch's own, folding it in is suggested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np

from backend.analysis.bars import EDGE_FRACTION, regions
from backend.analysis.features import GridFeatures, half_lines
from backend.analysis.meter import MeterRun
from backend.analysis.tempo_map import SegmentFit, TempoMapConfig
from backend.schema.models import BeatsFile, MeterSegment, TempoSegment

Kind = Literal["half", "double", "fold"]
_Class = Literal["half", "plain", "double", "unknown", "excluded"]

# column of each band in GridFeatures.values
LOW, MID, HIGH = 0, 1, 2


@dataclass(frozen=True)
class NotationConfig:
    # bars per window, and how far a window moves
    window_bars: int = 4
    # a run of half or double bars shorter than this, in bars of the faster of the two tempos,
    # isn't a section a chart would retime. so 8 bars of the grid for half, 4 for double
    min_span_bars: int = 8
    # in the folded snare profile, against its strongest position: under single_ratio a position
    # is empty, over present_ratio it has a hit. the kick leaks about 0.35 into the snare band
    # on the test drums, real kicks with a hard beater will leak more. tuned on synthetic drums
    single_ratio: float = 0.5
    present_ratio: float = 0.6
    # the kick band's strongest hit has to reach this share of the snare band's, below that it's
    # leakage from something else. clicks leave under 0.05 there, the test drums 1.0
    kick_min: float = 0.2
    # fold: the stretch has to be near the edge (tempo map's edge rule) and the carried grid has
    # to catch at least this share of the onsets the two grids catch together
    fold_min_score: float = 0.5

    def __post_init__(self) -> None:
        if self.window_bars < 1 or self.min_span_bars < 1:
            raise ValueError("window and span lengths have to be at least one bar")
        if not 0 < self.single_ratio < self.present_ratio <= 1:
            raise ValueError("notation thresholds are out of range")


@dataclass(frozen=True)
class Suggestion:
    start_ms: float
    end_ms: float
    kind: Kind
    suggested_bpm: float
    grid_bpm: float
    score: float


@dataclass(frozen=True)
class Segment:
    """A tempo segment as the suggestions read it, from the analysis or from a stored report."""

    start_ms: float
    end_ms: float
    bpm: float
    anchor_ms: float
    # (start_ms, end_ms) of each ratio merged section
    felt: tuple[tuple[float, float], ...] = ()

    @property
    def period_ms(self) -> float:
        return 60000.0 / self.bpm


def from_fits(segments: Sequence[SegmentFit]) -> list[Segment]:
    return [
        Segment(s.start_ms, s.end_ms, s.fit.bpm, s.anchor_ms, tuple((m.start_ms, m.end_ms) for m in s.ratio_merges))
        for s in segments
    ]


def from_report(tempo_map: Sequence[TempoSegment]) -> list[Segment]:
    return [
        Segment(t.start_ms, t.end_ms, t.bpm, t.anchor_ms, tuple((m.start_ms, m.end_ms) for m in t.ratio_merged))
        for t in tempo_map
    ]


def feature_positions(segments: Sequence[Segment], song_start_ms: float, song_end_ms: float,
                      config: TempoMapConfig = TempoMapConfig()) -> np.ndarray:
    """Every position the suggestions read: each segment's lines and half lines, plus the fold check's."""
    parts = [half_lines(s.anchor_ms, s.period_ms, s.start_ms, s.end_ms) for s in segments]
    for run, n in _edge_runs(segments, song_start_ms, song_end_ms, config):
        start, end = segments[run[0]].start_ms, segments[run[-1]].end_ms
        parts.append(half_lines(segments[n].anchor_ms, segments[n].period_ms, start, end))
    return np.concatenate(parts) if parts else np.zeros(0)


# --- half and double ---


def _classify(profile: np.ndarray, config: NotationConfig, phase: int | None = None) -> tuple[_Class, float, int]:
    """Class, how clear it is (0 to 1), and the strongest position, for one folded 8 step profile.

    With phase, the hits are read from there instead of the strongest position, for one bar
    read against the run it's next to.

    Clear is the contrast between where the hits are and where nothing should be: with the
    empty positions at a third of the hits it's 0.67. A breakdown or a fill has no position
    that stands out like that and comes back unknown.
    """
    if not np.all(np.isfinite(profile)):
        return "unknown", 0.0, 0
    r = int(np.argmax(profile)) if phase is None else phase
    top = float(profile[r])
    if top <= 0:
        return "unknown", 0.0, r
    def at(step: int) -> float:
        return float(profile[(r + step) % 8]) / top

    v4 = at(4)
    near = (at(2), at(6))
    odd = max(at(1), at(3), at(5), at(7))
    single, present = config.single_ratio, config.present_ratio
    if v4 >= present and min(near) >= present and odd < single:
        return "double", min(v4, *near, 1 - odd), r
    if v4 >= present and max(near) < single:
        return "plain", min(v4, 1 - max(near)), r
    if v4 < single and max(near) < single:
        return "half", 1 - max(v4, *near), r
    return "unknown", 0.0, r


# where the kick goes against the snare's strongest position r, in half beat steps: between the
# snare hits, half a backbeat from them
_KICK_STEPS: dict[str, tuple[int, ...]] = {"plain": (2, 6), "half": (4,), "double": (1, 3, 5, 7)}


def _kick_share(kick: np.ndarray, snare: np.ndarray, kind: _Class, r: int, config: NotationConfig) -> float:
    """How strong the kick is where this feel puts it, against its own strongest hit, 0 when it isn't there."""
    if kind not in _KICK_STEPS or not np.all(np.isfinite(kick)):
        return 0.0
    top = float(kick.max())
    if top <= 0 or top < config.kick_min * float(snare.max()):
        return 0.0
    share = max(float(kick[(r + step) % 8]) for step in _KICK_STEPS[kind]) / top
    return share if share >= config.present_ratio else 0.0


@dataclass(frozen=True)
class _Bars:
    # one 4/4 region of one tempo segment
    tempo: int
    starts_ms: np.ndarray
    bar_ms: float
    period_ms: float
    # (bars, 8 steps, 3 bands), nan where there's no feature or the bar is left out
    values: np.ndarray


def _bars_in(segments: Sequence[Segment], meter: Sequence[MeterRun | MeterSegment], features: GridFeatures) -> list[_Bars]:
    out: list[_Bars] = []
    for r in regions(segments, meter):
        numerator, denominator = (4, 4) if r.meter < 0 else (meter[r.meter].numerator, meter[r.meter].denominator)
        if (numerator, denominator) != (4, 4):
            continue
        s = segments[r.tempo]
        lo = max(r.from_ms, s.start_ms - EDGE_FRACTION * r.period_ms)
        hi = min(r.stop_ms, s.end_ms)
        k0 = int(np.ceil((lo - r.ref_ms) / r.bar_ms - 1e-9))
        starts = []
        k = k0
        while r.ref_ms + (k + 1) * r.bar_ms <= hi + EDGE_FRACTION * r.period_ms:
            starts.append(r.ref_ms + k * r.bar_ms)
            k += 1
        if not starts:
            continue
        starts_ms = np.array(starts)
        steps = starts_ms[:, None] + np.arange(8)[None, :] * r.period_ms / 2.0
        values = features.lookup(steps.ravel()).reshape(len(starts), 8, -1)
        for felt_start, felt_end in s.felt:
            # another pulse in there, a bar that touches it says nothing about this grid's feel
            touches = (starts_ms < felt_end) & (starts_ms + r.bar_ms > felt_start)
            values[touches] = np.nan
        out.append(_Bars(r.tempo, starts_ms, r.bar_ms, r.period_ms, values))
    return out


def _bar_classes(bars: _Bars, config: NotationConfig) -> tuple[list[_Class], np.ndarray]:
    """Each bar's class by the windows it's in, and the score of that class for the bar."""
    n = len(bars.starts_ms)
    w = config.window_bars
    votes: list[dict[str, list[float]]] = [{} for _ in range(n)]
    excluded = np.any(~np.isfinite(bars.values[:, :, MID]), axis=1)
    # windows hang off both ends, shorter there, so the first and last bars get as many votes
    for start in range(1 - w, n):
        a, z = max(start, 0), min(start + w, n)
        if excluded[a:z].any():
            continue
        mid = np.mean(bars.values[a:z, :, MID], axis=0)
        snare, clear, r = _classify(mid, config)
        if snare == "unknown":
            continue
        kick = _kick_share(np.mean(bars.values[a:z, :, LOW], axis=0), mid, snare, r, config)
        if snare != "plain" and kick == 0.0:
            # no backbeat under it, whatever is on every beat it isn't a feel to retime
            continue
        score = clear * (kick if snare != "plain" else 1.0)
        for b in range(a, z):
            votes[b].setdefault(snare, []).append(score)
    classes: list[_Class] = []
    scores = np.zeros(n)
    for b in range(n):
        if excluded[b]:
            classes.append("excluded")
            continue
        if not votes[b]:
            classes.append("unknown")
            continue
        best = max(votes[b], key=lambda c: (len(votes[b][c]), np.mean(votes[b][c])))
        classes.append(best)  # type: ignore[arg-type]
        # a bar that half its windows called something else is less sure
        total = sum(len(v) for v in votes[b].values())
        scores[b] = float(np.mean(votes[b][best])) * len(votes[b][best]) / total
    return classes, scores


def _refine(bars: _Bars, classes: list[_Class], a: int, b: int, kind: _Class, config: NotationConfig) -> tuple[int, int]:
    # the windows blur an edge by a bar or two, so each edge moves to where the bars on their
    # own, read at the run's phase, change between kind and not
    _, _, phase = _classify(np.mean(bars.values[a:b, :, MID], axis=0), config)

    def own(i: int) -> bool:
        return classes[i] != "excluded" and _classify(bars.values[i, :, MID], config, phase)[0] == kind

    reach = config.window_bars // 2
    for _ in range(reach):
        if a > 0 and own(a - 1):
            a -= 1
        elif a < b - 1 and not own(a):
            a += 1
    for _ in range(reach):
        if b < len(classes) and own(b):
            b += 1
        elif b > a + 1 and not own(b - 1):
            b -= 1
    return a, b


def feel_suggestions(
    segments: Sequence[Segment],
    meter: Sequence[MeterRun | MeterSegment],
    features: GridFeatures,
    config: NotationConfig = NotationConfig(),
) -> list[Suggestion]:
    out: list[Suggestion] = []
    for bars in _bars_in(segments, meter, features):
        s = segments[bars.tempo]
        classes, scores = _bar_classes(bars, config)
        b = 0
        while b < len(classes):
            kind = classes[b]
            if kind not in ("half", "double"):
                b += 1
                continue
            e = b
            while e < len(classes) and classes[e] == kind:
                e += 1
            a, z = _refine(bars, classes, b, e, kind, config)
            if (z - a) * (2 if kind == "double" else 1) >= config.min_span_bars:
                start = max(s.start_ms, float(bars.starts_ms[a]))
                end = min(s.end_ms, float(bars.starts_ms[z - 1]) + bars.bar_ms)
                factor = 0.5 if kind == "half" else 2.0
                score = float(np.mean(scores[b:e]))
                out.append(Suggestion(start, end, kind, s.bpm * factor, s.bpm, round(score, 3)))
            b = max(e, z)
    return out


# --- fold ---


def _edge_runs(segments: Sequence[Segment], song_start_ms: float, song_end_ms: float,
               config: TempoMapConfig) -> list[tuple[list[int], int]]:
    """(segments in the run, neighbour) for the start and the end of the song."""
    n = len(segments)
    if n < 2:
        return []
    song = max(song_end_ms - song_start_ms, 1e-9)
    found: list[tuple[list[int], int]] = []
    for ordered in (list(range(n)), list(range(n - 1, -1, -1))):
        best: tuple[list[int], int] | None = None
        for size in range(1, n):
            run = sorted(ordered[:size])
            neighbour = ordered[size]
            length = segments[run[-1]].end_ms - segments[run[0]].start_ms
            other = segments[neighbour]
            limit = max(config.edge_max_share * song, config.edge_max_bars * 4 * other.period_ms)
            if length > limit:
                break
            if other.end_ms - other.start_ms > length:
                best = (run, neighbour)
        if best is not None and best not in found:
            found.append(best)
    return found


def fold_suggestions(
    segments: Sequence[Segment],
    features: GridFeatures,
    song_start_ms: float,
    song_end_ms: float,
    tempo_config: TempoMapConfig = TempoMapConfig(),
    config: NotationConfig = NotationConfig(),
) -> list[Suggestion]:
    out: list[Suggestion] = []
    for run, n in _edge_runs(segments, song_start_ms, song_end_ms, tempo_config):
        other = segments[n]
        start, end = segments[run[0]].start_ms, segments[run[-1]].end_ms
        carried = features.lookup(half_lines(other.anchor_ms, other.period_ms, start, end)).sum(axis=1)
        own = np.concatenate([
            features.lookup(half_lines(segments[i].anchor_ms, segments[i].period_ms, segments[i].start_ms,
                                       segments[i].end_ms)).sum(axis=1)
            for i in run
        ])
        carried, own = carried[np.isfinite(carried)], own[np.isfinite(own)]
        if len(carried) == 0 or len(own) == 0:
            continue
        on, off = float(np.median(carried)), float(np.median(own))
        if on + off <= 0:
            continue
        score = on / (on + off)
        if score >= config.fold_min_score:
            out.append(Suggestion(start, end, "fold", other.bpm, segments[run[0]].bpm, round(score, 3)))
    return out


def stored_features(beats: BeatsFile) -> GridFeatures:
    times = np.array([f.time_ms for f in beats.grid_features], dtype=np.float64)
    values = np.array([[f.low, f.mid, f.high] for f in beats.grid_features], dtype=np.float64).reshape(-1, 3)
    order = np.argsort(times, kind="stable")
    return GridFeatures(times_ms=times[order], values=values[order])


def suggest_from_files(
    tempo_map: Sequence[TempoSegment],
    meter_map: Sequence[MeterSegment],
    beats: BeatsFile,
    song_start_ms: float,
    song_end_ms: float,
    tempo_config: TempoMapConfig = TempoMapConfig(),
    config: NotationConfig = NotationConfig(),
) -> list[Suggestion]:
    """The suggestions again from a stored report's maps and its beats file, no audio needed.

    Only lines up with the stored features while the tempo map is the one the analysis wrote,
    an edited grid reads positions that were never measured and comes back with less.
    """
    segments = from_report(tempo_map)
    features = stored_features(beats)
    return feel_suggestions(segments, meter_map, features, config) + fold_suggestions(
        segments, features, song_start_ms, song_end_ms, tempo_config, config
    )
