"""Band onset strengths at grid positions, what meter and notation read from the audio.

Spectral flux in three bands (kick, snare and most attacks, hats), taken as the biggest
value within a few ms of each position. Only these numbers go into the beats file, so the
notation detector can run again later from beats.json without the audio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# hz. low is kick and bass attacks, mid the snare's body and most pitched attacks, high hats,
# cymbals and the snare's noise. the gap between mid and high keeps hats out of the snare band
BANDS: tuple[tuple[str, float, float], ...] = (("low", 30.0, 150.0), ("mid", 150.0, 3000.0), ("high", 5000.0, 16000.0))
# 1024 samples is 23 ms at 44.1 khz, about 43 hz per bin, enough to keep the kick band apart
FFT_AT_44K = 1024
HOP_AT_44K = 256
# frames at a time, a whole song's spectrogram at once would be a few hundred MB
_CHUNK_FRAMES = 2048
# biggest flux within this of a position, capped at an eighth of a beat so half lines don't overlap
WINDOW_MS = 20.0


@dataclass(frozen=True)
class BandFlux:
    """Per-frame flux in each band over a stretch of the song."""

    times_ms: np.ndarray
    # (frames, bands)
    flux: np.ndarray


@dataclass(frozen=True)
class GridFeatures:
    times_ms: np.ndarray
    # (positions, bands), low, mid, high
    values: np.ndarray

    def lookup(self, times_ms: np.ndarray, tolerance_ms: float = 1.0) -> np.ndarray:
        """Values at these times, nan where no stored position is within tolerance."""
        times = np.asarray(times_ms, dtype=np.float64)
        out = np.full((len(times), self.values.shape[1]), np.nan)
        if len(self.times_ms) == 0 or len(times) == 0:
            return out
        k = np.clip(np.searchsorted(self.times_ms, times), 1, len(self.times_ms) - 1)
        left, right = self.times_ms[k - 1], self.times_ms[k]
        nearest = np.where(np.abs(times - left) <= np.abs(times - right), k - 1, k)
        ok = np.abs(self.times_ms[nearest] - times) <= tolerance_ms
        out[ok] = self.values[nearest[ok]]
        return out


def _sizes(sample_rate: int) -> tuple[int, int]:
    scale = sample_rate / 44100.0
    n_fft = int(2 ** round(np.log2(FFT_AT_44K * scale)))
    return n_fft, max(1, int(round(HOP_AT_44K * scale)))


def band_flux(samples: np.ndarray, sample_rate: int, start_ms: float, end_ms: float) -> BandFlux:
    """Positive spectral flux per band over [start_ms, end_ms], a little padding either side."""
    if samples.ndim != 1:
        raise ValueError("band_flux expects mono samples")
    n_fft, hop = _sizes(sample_rate)
    pad = n_fft
    lo = max(0, int(start_ms / 1000.0 * sample_rate) - pad)
    hi = min(len(samples), int(np.ceil(end_ms / 1000.0 * sample_rate)) + pad)
    seg = np.asarray(samples[lo:hi], dtype=np.float32)
    if len(seg) < n_fft:
        seg = np.pad(seg, (0, n_fft - len(seg)))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    masks = [(freqs >= f_lo) & (freqs < f_hi) for _, f_lo, f_hi in BANDS]
    window = np.hanning(n_fft + 2)[1:-1].astype(np.float32)
    num_frames = 1 + (len(seg) - n_fft) // hop
    flux = np.zeros((num_frames, len(BANDS)))
    prev: np.ndarray | None = None
    for a in range(0, num_frames, _CHUNK_FRAMES):
        b = min(num_frames, a + _CHUNK_FRAMES)
        idx = np.arange(n_fft)[None, :] + hop * np.arange(a, b)[:, None]
        mag = np.abs(np.fft.rfft(seg[idx] * window, axis=1))
        # linear magnitude, same as the snap, so an accent twice as loud reads twice as strong
        stacked = mag if prev is None else np.vstack((prev[None, :], mag))
        rise = np.maximum(0.0, np.diff(stacked, axis=0))
        if prev is None:
            rise = np.vstack((np.zeros((1, mag.shape[1])), rise))
        for j, mask in enumerate(masks):
            flux[a:b, j] = rise[:, mask].sum(axis=1)
        prev = mag[-1]
    # frame centre, the rise belongs to the frame that has the new energy in it
    times = (lo + hop * np.arange(num_frames) + n_fft / 2.0) / sample_rate * 1000.0
    return BandFlux(times_ms=times, flux=flux)


def strengths_at(bands: BandFlux, times_ms: np.ndarray, window_ms: float = WINDOW_MS) -> np.ndarray:
    """Biggest flux per band within window_ms of each time, (len(times), bands)."""
    times = np.asarray(times_ms, dtype=np.float64)
    out = np.zeros((len(times), bands.flux.shape[1]))
    if len(bands.times_ms) == 0:
        return out
    lo = np.searchsorted(bands.times_ms, times - window_ms, side="left")
    hi = np.searchsorted(bands.times_ms, times + window_ms, side="right")
    for i, (a, b) in enumerate(zip(lo, hi)):
        if b > a:
            out[i] = bands.flux[a:b].sum(axis=0)
    return out


def grid_features(bands: BandFlux, times_ms: np.ndarray, window_ms: float = WINDOW_MS) -> GridFeatures:
    """Strengths at these positions, sorted and on one scale for the whole song.

    The scale is the median total over the positions, so a typical position sums to about 1
    and the three bands stay comparable with each other.
    """
    times = np.unique(np.round(np.asarray(times_ms, dtype=np.float64), 3))
    values = strengths_at(bands, times, window_ms)
    total = values.sum(axis=1)
    scale = float(np.median(total[total > 0])) if np.any(total > 0) else 1.0
    return GridFeatures(times_ms=times, values=values / scale)


def half_lines(anchor_ms: float, period_ms: float, start_ms: float, end_ms: float) -> np.ndarray:
    """Every grid line and half line of one grid inside [start_ms, end_ms)."""
    step = period_ms / 2.0
    first = int(np.ceil((start_ms - anchor_ms) / step - 1e-9))
    last = int(np.floor((end_ms - anchor_ms) / step - 1e-9))
    return anchor_ms + step * np.arange(first, last + 1)
