import numpy as np
import pytest

from backend.analysis.decode import load_mono
from backend.analysis.trim import DEFAULT_THRESHOLD_DB, TrimError, find_trim, stretch_level
from tests.synth import ClickTrackSpec, cached_click_wav, click_track

# half a coarse window, anything past this is the fine pass not doing its job
TRIM_TOLERANCE_MS = 10.0

# 16 beats is plenty to trim, keeps the cached wavs small
BEATS = 16


def _load(spec: ClickTrackSpec):
    path, track = cached_click_wav(spec)
    samples, sample_rate = load_mono(path)
    assert sample_rate == spec.sample_rate
    return samples, sample_rate, track


@pytest.mark.parametrize("noise_floor_db", [None, -90.0, -80.0], ids=["clean", "noise-90", "noise-80"])
@pytest.mark.parametrize(
    "padding",
    [(2.0, 2.0), (0.37, 1.13), (5.0, 0.01)],
    ids=["lead2.0-tail2.0", "lead0.37-tail1.13", "lead5.0-tail0.01"],
)
@pytest.mark.parametrize("sample_rate", [44100, 48000], ids=["44k", "48k"])
def test_trim_matches_ground_truth(sample_rate, padding, noise_floor_db):
    lead, tail = padding
    # noise-80 sits only a couple of db under the threshold, that's the hard one
    spec = ClickTrackSpec(
        beats=BEATS,
        sample_rate=sample_rate,
        lead_silence_s=lead,
        tail_silence_s=tail,
        noise_floor_db=noise_floor_db,
    )
    samples, sr, track = _load(spec)

    trim = find_trim(samples, sr)

    start_err = trim.start_ms - track.content_start_ms
    end_err = trim.end_ms - track.content_end_ms
    assert abs(start_err) <= TRIM_TOLERANCE_MS, f"start off by {start_err:+.3f} ms"
    assert abs(end_err) <= TRIM_TOLERANCE_MS, f"end off by {end_err:+.3f} ms"


def test_sound_from_the_first_sample_starts_at_zero():
    samples, sr, track = _load(ClickTrackSpec(beats=BEATS, lead_silence_s=0.0))
    assert track.content_start_ms == 0.0

    trim = find_trim(samples, sr)

    # not "close to 0", the file edge is special cased
    assert trim.start_ms == 0.0


def test_sound_until_the_last_sample_ends_at_the_duration():
    samples, sr, track = _load(ClickTrackSpec(beats=BEATS, tail_silence_s=0.0))

    trim = find_trim(samples, sr)

    assert trim.end_ms == pytest.approx(len(samples) / sr * 1000.0)
    assert trim.end_ms == pytest.approx(track.duration_ms)


def test_noise_floor_above_the_threshold_trims_to_the_whole_file():
    # known limit from docs/decisions.md, a floor above -60 db relative to the peak is "sound"
    samples, sr, track = _load(ClickTrackSpec(beats=BEATS, noise_floor_db=-70.0))

    trim = find_trim(samples, sr)

    assert trim.start_ms == 0.0
    assert trim.end_ms == pytest.approx(track.duration_ms)


def test_all_zero_audio_is_silent():
    with pytest.raises(TrimError, match="audio is silent"):
        find_trim(np.zeros(3 * 44100, dtype=np.float32), 44100)


def test_audio_shorter_than_one_window_is_refused():
    # 20 ms is 882 samples at 44.1 khz
    with pytest.raises(TrimError, match="shorter than one analysis window"):
        find_trim(np.full(100, 0.5, dtype=np.float32), 44100)


def test_stereo_samples_are_refused():
    with pytest.raises(ValueError, match="mono"):
        find_trim(np.zeros((44100, 2), dtype=np.float32), 44100)


@pytest.mark.parametrize("noise_floor_db", [None, -90.0, -70.0], ids=["clean", "noise-90", "noise-70"])
@pytest.mark.parametrize("strict_db", [-20.0, -40.0], ids=["-20db", "-40db"])
def test_stricter_threshold_never_widens(strict_db, noise_floor_db):
    # noise-70 is above the -60 threshold so the loose pass takes the whole file,
    # which is the only case here where the strict one has anything to cut
    track = click_track(ClickTrackSpec(beats=BEATS, noise_floor_db=noise_floor_db))
    sr = track.sample_rate

    loose = find_trim(track.samples, sr, threshold_db=DEFAULT_THRESHOLD_DB)
    strict = find_trim(track.samples, sr, threshold_db=strict_db)

    assert strict.start_ms >= loose.start_ms
    assert strict.end_ms <= loose.end_ms


@pytest.mark.parametrize("sample_rate", [22050, 44100, 48000])
def test_stretch_level_is_against_the_median_of_the_song(sample_rate):
    # 60 s of noise, the last 10 s 20 db quieter, like a fade that has already gone down
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(60 * sample_rate) * 0.1
    samples[50 * sample_rate:] *= 0.1

    level = stretch_level(samples, sample_rate, 0.0, 60000.0)

    assert level(0.0, 50000.0) == pytest.approx(0.0, abs=0.5)
    assert level(50000.0, 60000.0) == pytest.approx(-20.0, abs=0.5)
    # a stretch right next to the change reads its own side of it
    assert level(49000.0, 50000.0) == pytest.approx(0.0, abs=0.5)
    assert level(50000.0, 51000.0) == pytest.approx(-20.0, abs=0.5)

