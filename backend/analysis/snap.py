"""Onset snap: move each tracked beat onto the nearest strong onset close to it.

madmom works at 100 fps, so its beats are 10 ms quantized and land early on
clicks. A short-window spectral flux, computed only around each beat, puts
them back on the attack.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_WINDOW_MS = 20.0
# 256 samples is ~5.8 ms at 44.1 khz, scaled so 48 khz gets the same window length
# shorter windows sit closer to the attack, see docs/decisions.md for the measured bias
FFT_AT_44K = 256
HOP_DIVISOR = 8
# a peak counts as strong if it's at least this fraction of the biggest peak in its window
PEAK_FRACTION = 0.5
# and the biggest peak in the window has to reach this fraction of the median over all beats,
# otherwise there's no onset worth snapping to (quiet passage, beat in a gap)
# tuned on click tracks only, revisit on real songs
MIN_STRENGTH = 0.2


@dataclass(frozen=True)
class SnapResult:
    times_ms: np.ndarray
    # false where no strong onset was found and the raw beat was kept
    snapped: np.ndarray
    window_ms: float
    shift_ms: float = 0.0


def _fft_size(sample_rate: int) -> int:
    n = int(round(FFT_AT_44K * sample_rate / 44100.0))
    return n + (n % 2)


def _local_flux(samples: np.ndarray, center: int, half_window: int, n_fft: int, hop: int) -> tuple[np.ndarray, np.ndarray]:
    # flux around one sample index, plus where each value sits in samples
    # only this little stretch gets an fft, a 0.7 ms hop over a whole song would be ~170 MB
    start = center - half_window - n_fft
    stop = center + half_window + n_fft
    seg = np.zeros(stop - start, dtype=np.float64)
    lo, hi = max(0, start), min(len(samples), stop)
    if hi > lo:
        seg[lo - start:hi - start] = samples[lo:hi]

    num_frames = 1 + (len(seg) - n_fft) // hop
    frames = np.arange(n_fft)[None, :] + hop * np.arange(num_frames)[:, None]
    window = np.hanning(n_fft + 2)[1:-1]
    # linear magnitude on purpose, log compression pulls the peak earlier by a couple of ms
    mag = np.abs(np.fft.rfft(seg[frames] * window, axis=1))
    flux = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    # the rise between frame j-1 and j belongs to frame j, the one that has the new energy in it
    times = start + np.arange(1, num_frames) * hop + n_fft / 2.0
    return flux, times


def _peaks(flux: np.ndarray) -> np.ndarray:
    if len(flux) < 3:
        return np.zeros(0, dtype=np.int64)
    mid = flux[1:-1]
    return np.flatnonzero((mid > flux[:-2]) & (mid >= flux[2:]) & (mid > 0.0)) + 1


def _interpolated(flux: np.ndarray, k: int) -> float:
    a, b, c = flux[k - 1], flux[k], flux[k + 1]
    denom = a - 2.0 * b + c
    if denom >= 0.0:
        return 0.0
    return float(0.5 * (a - c) / denom)


def _window_peaks(
    samples: np.ndarray, sample_rate: int, times_ms: np.ndarray, window_ms: float
) -> tuple[list[tuple[np.ndarray, np.ndarray] | None], np.ndarray]:
    # flux peaks within the window around each time: (strengths, peak times in samples) or None,
    # plus the biggest peak per window, 0 where there's none
    n_fft = _fft_size(sample_rate)
    hop = max(1, n_fft // HOP_DIVISOR)
    half_window = int(round(window_ms / 1000.0 * sample_rate))
    found: list[tuple[np.ndarray, np.ndarray] | None] = []
    biggest = np.zeros(len(times_ms))
    for i, t_ms in enumerate(times_ms):
        center = int(round(t_ms / 1000.0 * sample_rate))
        flux, times = _local_flux(samples, center, half_window, n_fft, hop)
        peaks = _peaks(flux)
        peaks = peaks[np.abs(times[peaks] - center) <= half_window]
        if len(peaks) == 0:
            found.append(None)
            continue
        peak_times = np.array([times[k] + _interpolated(flux, k) * hop for k in peaks])
        found.append((flux[peaks], peak_times))
        biggest[i] = flux[peaks].max()
    return found, biggest


def onset_strengths(
    samples: np.ndarray, sample_rate: int, times_ms: np.ndarray, window_ms: float = DEFAULT_WINDOW_MS
) -> np.ndarray:
    """Biggest flux peak within window_ms of each time, 0 where there's no peak at all."""
    if samples.ndim != 1:
        raise ValueError("onset_strengths expects mono samples")
    _, biggest = _window_peaks(samples, sample_rate, np.asarray(times_ms, dtype=np.float64), window_ms)
    return biggest


def snap_to_onsets(
    samples: np.ndarray,
    sample_rate: int,
    beat_times_ms: np.ndarray,
    window_ms: float = DEFAULT_WINDOW_MS,
    shift_ms: float = 0.0,
) -> SnapResult:
    """Snap each beat onto the nearest strong onset within window_ms.

    shift_ms is added to every beat first, it's how a tracker's known bias is taken out
    before the search. A beat with nothing to snap to keeps the shifted time.
    """
    if samples.ndim != 1:
        raise ValueError("snap_to_onsets expects mono samples")
    if window_ms <= 0:
        raise ValueError("snap window must be positive")

    beats = np.asarray(beat_times_ms, dtype=np.float64) + shift_ms
    # two passes, the strength floor needs every window's biggest peak first
    found, biggest = _window_peaks(samples, sample_rate, beats, window_ms)

    with_peaks = biggest[biggest > 0]
    floor = MIN_STRENGTH * float(np.median(with_peaks)) if len(with_peaks) else np.inf

    out = beats.copy()
    snapped = np.zeros(len(beats), dtype=bool)
    for i, entry in enumerate(found):
        if entry is None or biggest[i] < floor:
            continue
        strengths, peak_times = entry
        strong = peak_times[strengths >= PEAK_FRACTION * biggest[i]]
        center = beats[i] / 1000.0 * sample_rate
        nearest = strong[np.argmin(np.abs(strong - center))]
        out[i] = nearest / sample_rate * 1000.0
        snapped[i] = True

    return SnapResult(times_ms=out, snapped=snapped, window_ms=window_ms, shift_ms=shift_ms)
