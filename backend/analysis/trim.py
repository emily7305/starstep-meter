"""Trim: find where sound starts and ends. Reports boundaries, never cuts audio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# relative to the loudest 20 ms frame, not dbfs, so quiet masters trim the same as loud ones
# not sure -60 is right for real songs yet, tuned on synthetic clicks with a -90 dbfs noise floor
DEFAULT_THRESHOLD_DB = -60.0
# coarse pass, ~5 ms hop / ~20 ms window
HOP_MS = 5.0
WINDOW_MS = 20.0
# fine pass around each coarse boundary, 1 ms windows at every sample
FINE_WINDOW_MS = 1.0


class TrimError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrimResult:
    start_ms: float
    end_ms: float
    threshold_db: float
    peak_rms: float


def _moving_mean_square(x: np.ndarray, window: int) -> np.ndarray:
    # cumsum trick, value i is the mean square of x[i:i + window]
    # float64 or the cumsum drifts on long files
    cs = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    return (cs[window:] - cs[:-window]) / window


def find_trim(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    hop_ms: float = HOP_MS,
    window_ms: float = WINDOW_MS,
) -> TrimResult:
    if samples.ndim != 1:
        raise ValueError("find_trim expects mono samples")

    hop = max(1, int(round(hop_ms / 1000.0 * sample_rate)))
    window = max(1, int(round(window_ms / 1000.0 * sample_rate)))
    fine = max(1, int(round(FINE_WINDOW_MS / 1000.0 * sample_rate)))
    to_ms = 1000.0 / sample_rate

    if len(samples) < window:
        raise TrimError("audio is shorter than one analysis window")

    coarse_msq = _moving_mean_square(samples, window)[::hop]
    peak_msq = float(coarse_msq.max())
    if peak_msq <= 0.0:
        raise TrimError("audio is silent")

    # msq = mean square, compared against the squared threshold so there's no sqrt per frame
    thresh_msq = peak_msq * 10.0 ** (threshold_db / 10.0)
    loud = np.flatnonzero(coarse_msq > thresh_msq)
    first = int(loud[0]) * hop
    last = int(loud[-1]) * hop

    # the coarse window can be up to 20 ms early or late, so redo the edges at 1 ms resolution
    fine_msq = _moving_mean_square(samples, fine)
    span = max(1, window - fine + 1)

    # anchor on the loudest 1 ms inside the first loud frame (always above threshold,
    # a loud 20 ms window has at least one loud 1 ms window in it), then walk back to
    # where that loud run starts. first-crossing-in-a-range picked up noise blips
    # when the floor sat a couple of db under the threshold
    anchor = first + int(np.argmax(fine_msq[first:first + span]))
    lo = max(0, anchor - 2 * window)
    quiet = np.flatnonzero(fine_msq[lo:anchor] <= thresh_msq)
    start_idx = lo + int(quiet[-1]) + 1 if len(quiet) else lo

    anchor = last + int(np.argmax(fine_msq[last:last + span]))
    hi = min(len(fine_msq), anchor + 2 * window)
    quiet = np.flatnonzero(fine_msq[anchor:hi] <= thresh_msq)
    end_idx = anchor + int(quiet[0]) - 1 if len(quiet) else hi - 1

    # window centres, so both edges are within half a fine window of the real crossing
    # except at the file edges, where sound from sample 0 really does start at 0
    half = fine / 2.0
    start_ms = 0.0 if start_idx == 0 else (start_idx + half) * to_ms
    end_ms = len(samples) * to_ms if end_idx >= len(fine_msq) - 1 else (end_idx + half) * to_ms
    return TrimResult(
        start_ms=start_ms,
        end_ms=end_ms,
        threshold_db=threshold_db,
        peak_rms=float(np.sqrt(peak_msq)),
    )
