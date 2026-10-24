"""Tempo, milestone 1: one global bpm for the trimmed region.

This is a coarse placeholder. Milestone 2 replaces it with a regression
over tracked beats, which is where the two-decimal accuracy has to come from.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

from backend.analysis.tempo_range import TempoRange

# 256 samples at 44.1 khz is ~5.8 ms per onset frame, scaled so 48 khz gets the same frame length
ONSET_HOP_AT_44K = 256
# the faster of two octave candidates wins if its autocorrelation peak is at least this
# fraction of the strongest one. tuned on click tracks only, real music will need more
OCTAVE_SUPPORT = 0.5
# librosa's coarse guess leans towards 120 bpm, a 270 bpm click track comes out at 90,
# so thirds and 3:2 are candidates too and not just halves and doubles
CANDIDATE_RATIOS = (1 / 3, 1 / 2, 2 / 3, 1.0, 3 / 2, 2.0, 3.0)
# lag refinement keeps going out to this many beats, or half the envelope, whichever is shorter
REFINE_MAX_BEATS = 32
MIN_DURATION_S = 3.0


class TempoError(RuntimeError):
    pass


@dataclass(frozen=True)
class TempoResult:
    bpm: float
    # what librosa.feature.tempo said before the octave check and refinement, for debugging
    coarse_bpm: float
    octave_support: dict[float, float]
    hop_length: int
    frame_rate: float


def onset_hop(sample_rate: int) -> int:
    return max(1, int(round(ONSET_HOP_AT_44K * sample_rate / 44100.0)))


def _unbiased_autocorrelation(env: np.ndarray) -> np.ndarray:
    x = env - env.mean()
    ac = librosa.autocorrelate(x)
    # divide by the overlap count so long lags aren't pulled down (that tilts the peaks toward shorter lags)
    ac = ac / np.arange(len(x), 0, -1)
    return ac / ac[0] if ac[0] > 0 else ac


def _peak_near(ac: np.ndarray, lag: float, rel_width: float = 0.03) -> float:
    lo = max(1, int(np.floor(lag * (1.0 - rel_width))))
    hi = min(len(ac) - 1, int(np.ceil(lag * (1.0 + rel_width))))
    if lo > hi:
        return 0.0
    return float(ac[lo:hi + 1].max())


def _pick_octave(ac: np.ndarray, frame_rate: float, coarse_bpm: float, tempo_range: TempoRange) -> tuple[float, dict[float, float]]:
    support: dict[float, float] = {}
    # candidates outside the range are never picked
    for bpm in (coarse_bpm * ratio for ratio in CANDIDATE_RATIOS):
        if tempo_range.contains(bpm):
            support[bpm] = _peak_near(ac, 60.0 * frame_rate / bpm)
    if not support:
        # every candidate is out of range, keep what librosa said
        return coarse_bpm, {coarse_bpm: _peak_near(ac, 60.0 * frame_rate / coarse_bpm)}

    strongest = max(support.values())
    # a click at every beat also lines up at 2 beats, 3 beats... so slower candidates always look
    # supported. the fastest candidate that still has a real peak is the actual pulse
    for bpm in sorted(support, reverse=True):
        if support[bpm] >= OCTAVE_SUPPORT * strongest:
            return bpm, support
    return coarse_bpm, support


def _parabolic_peak(ac: np.ndarray, i: int) -> float:
    a, b, c = ac[i - 1], ac[i], ac[i + 1]
    denom = a - 2.0 * b + c
    if denom >= 0.0:
        return float(i)
    return i + 0.5 * (a - c) / denom


def _refine_period(ac: np.ndarray, period: float) -> float:
    # librosa's tempo bins are whole frame lags, ~1.4 bpm apart at 120 bpm with this hop,
    # which alone misses ±1 bpm at 174. so find the peak at k periods for k = 1, 2, 3...
    # with sub-frame interpolation and fit lag = k * period through all of them.
    # longer lags pin the period down more precisely, each one tightens the next search
    max_lag = min(len(ac) // 2, int(REFINE_MAX_BEATS * period))
    ks: list[int] = []
    lags: list[float] = []
    k = 1
    while k * period + 2 < max_lag:
        center = k * period
        half_width = max(2.0, 0.08 * period)
        lo = max(1, int(np.floor(center - half_width)))
        hi = min(len(ac) - 2, int(np.ceil(center + half_width)))
        i = lo + int(np.argmax(ac[lo:hi + 1]))
        if lo < i < hi:
            ks.append(k)
            lags.append(_parabolic_peak(ac, i))
            k_arr = np.asarray(ks, dtype=np.float64)
            period = float(np.dot(k_arr, lags) / np.dot(k_arr, k_arr))
        k += 1
    return period


def estimate_tempo(
    samples: np.ndarray,
    sample_rate: int,
    start_ms: float,
    end_ms: float,
    tempo_range: TempoRange = TempoRange(),
) -> TempoResult:
    start = int(round(start_ms / 1000.0 * sample_rate))
    end = int(round(end_ms / 1000.0 * sample_rate))
    region = samples[start:end]
    if len(region) < MIN_DURATION_S * sample_rate:
        raise TempoError(f"need at least {MIN_DURATION_S:g} s of audio between the trim points for a tempo estimate")

    hop = onset_hop(sample_rate)
    frame_rate = sample_rate / hop
    env = librosa.onset.onset_strength(y=region, sr=sample_rate, hop_length=hop)
    if not np.any(env > 0):
        raise TempoError("no onsets found in the trimmed region")

    coarse = float(librosa.feature.tempo(onset_envelope=env, sr=sample_rate, hop_length=hop)[0])
    if not coarse > 0:
        raise TempoError("tempo estimate failed")

    ac = _unbiased_autocorrelation(env)
    picked, support = _pick_octave(ac, frame_rate, coarse, tempo_range)
    period = _refine_period(ac, 60.0 * frame_rate / picked)
    bpm = 60.0 * frame_rate / period

    # refinement should only ever nudge, if it wandered more than ~3% something's off, keep the octave pick
    if abs(bpm - picked) / picked > 0.03:
        bpm = picked

    return TempoResult(
        bpm=bpm,
        coarse_bpm=coarse,
        octave_support={round(k, 3): round(v, 4) for k, v in support.items()},
        hop_length=hop,
        frame_rate=frame_rate,
    )
