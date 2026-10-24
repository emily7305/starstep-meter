import pytest

from backend.analysis.tempo_range import TempoRange
from backend.api.settings import Settings


def test_tempo_range_defaults_to_60_to_320():
    assert Settings().tempo_range == TempoRange(60.0, 320.0)


def test_tempo_range_comes_from_the_env(monkeypatch):
    monkeypatch.setenv("STARSTEP_MIN_BPM", "100")
    monkeypatch.setenv("STARSTEP_MAX_BPM", "400")

    assert Settings.from_env().tempo_range == TempoRange(100.0, 400.0)


@pytest.mark.parametrize(("low", "high"), [("300", "200"), ("0", "320"), ("120", "120")])
def test_a_bad_tempo_range_fails_at_startup(monkeypatch, low, high):
    monkeypatch.setenv("STARSTEP_MIN_BPM", low)
    monkeypatch.setenv("STARSTEP_MAX_BPM", high)

    with pytest.raises(ValueError, match="min_bpm"):
        Settings.from_env()


def test_a_non_number_names_the_variable(monkeypatch):
    monkeypatch.setenv("STARSTEP_MAX_BPM", "fast")

    with pytest.raises(ValueError, match="STARSTEP_MAX_BPM"):
        Settings.from_env()
