"""madmom_import_error, the health route that reports it, and how track_beats reacts to it."""

from __future__ import annotations

import builtins
import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.analysis import beats
from backend.analysis.beats import BeatTrackingError, track_beats
from backend.analysis.trim import find_trim
from backend.api import app as app_module
from backend.api.app import create_app
from backend.api.settings import Settings
from tests.synth import ClickTrackSpec, click_track

SPEC = ClickTrackSpec(bpm=120, beats=40, lead_silence_s=0.1375, accent_downbeats=True)
PKG_RESOURCES = "ModuleNotFoundError: No module named 'pkg_resources'"
NUMPY_ATTRIBUTE = "AttributeError: module 'numpy' has no attribute 'float'"


@pytest.fixture(autouse=True)
def fresh_cache():
    # the answer is cached for the whole process, a simulated failure must not outlive its test
    beats.madmom_import_error.cache_clear()
    yield
    beats.madmom_import_error.cache_clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def installed(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    # the route holds its own reference to the function, so both names need patching
    monkeypatch.setattr(beats, "madmom_available", lambda: value)
    monkeypatch.setattr(app_module, "madmom_available", lambda: value)


def fail_madmom_imports(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> list[str]:
    # every import of madmom or one of its submodules raises exc, returns the names that were tried
    real_import = builtins.__import__
    tried: list[str] = []

    def fake_import(name, *args, **kwargs):
        if name == "madmom" or name.startswith("madmom."):
            tried.append(name)
            raise exc
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    return tried


def fake_madmom(monkeypatch: pytest.MonkeyPatch, *, downbeat_names: tuple[str, ...]) -> None:
    # a madmom that imports, with only the given names in madmom.features.downbeats
    root = types.ModuleType("madmom")
    features = types.ModuleType("madmom.features")
    downbeats = types.ModuleType("madmom.features.downbeats")
    # a package needs a path before its submodules can be found
    root.__path__ = []  # type: ignore[attr-defined]
    features.__path__ = []  # type: ignore[attr-defined]
    for name in downbeat_names:
        setattr(downbeats, name, object)
    root.features = features  # type: ignore[attr-defined]
    features.downbeats = downbeats  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "madmom", root)
    monkeypatch.setitem(sys.modules, "madmom.features", features)
    monkeypatch.setitem(sys.modules, "madmom.features.downbeats", downbeats)


def prepare():
    track = click_track(SPEC)
    trim = find_trim(track.samples, track.sample_rate)
    return track, trim


# --- madmom_import_error ---


def test_import_error_is_none_when_madmom_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: False)
    tried = fail_madmom_imports(monkeypatch, AssertionError("not installed is not an import error, nothing to try"))

    assert beats.madmom_import_error() is None
    assert tried == []


@pytest.mark.parametrize(
    "exc",
    [
        ModuleNotFoundError("No module named 'pkg_resources'"),
        AttributeError("module 'numpy' has no attribute 'float'"),
        RuntimeError("boom"),
    ],
    ids=["missing module", "numpy attribute", "anything else"],
)
def test_import_error_names_the_exception_and_its_message(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    fail_madmom_imports(monkeypatch, exc)

    assert beats.madmom_import_error() == f"{type(exc).__name__}: {exc}"


def test_import_error_when_madmom_is_none_in_sys_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    monkeypatch.setitem(sys.modules, "madmom", None)

    error = beats.madmom_import_error()
    assert error is not None
    assert error.startswith("ModuleNotFoundError: ")


def test_import_error_is_none_when_both_imports_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    fake_madmom(monkeypatch, downbeat_names=("DBNDownBeatTrackingProcessor", "RNNDownBeatProcessor"))

    assert beats.madmom_import_error() is None


@pytest.mark.parametrize("missing", ["DBNDownBeatTrackingProcessor", "RNNDownBeatProcessor"])
def test_import_error_checks_the_two_names_the_tracker_uses(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    names = tuple(n for n in ("DBNDownBeatTrackingProcessor", "RNNDownBeatProcessor") if n != missing)
    fake_madmom(monkeypatch, downbeat_names=names)

    error = beats.madmom_import_error()
    assert error is not None
    assert error.startswith("ImportError: ")
    assert missing in error


def test_import_is_tried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    tried = fail_madmom_imports(monkeypatch, RuntimeError("boom"))

    first = beats.madmom_import_error()
    after_first = len(tried)
    assert after_first > 0
    assert beats.madmom_import_error() == first
    assert beats.madmom_import_error() == first
    assert len(tried) == after_first


# --- /api/health ---


@pytest.mark.parametrize(
    ("is_installed", "error", "madmom", "reported"),
    [
        (True, None, True, None),
        (True, PKG_RESOURCES, False, PKG_RESOURCES),
        (False, None, False, None),
    ],
    ids=["imports", "installed but broken", "not installed"],
)
def test_health_reports_madmom(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    is_installed: bool,
    error: str | None,
    madmom: bool,
    reported: str | None,
) -> None:
    installed(monkeypatch, is_installed)
    monkeypatch.setattr(app_module, "madmom_import_error", lambda: error)

    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["madmom"] is madmom
    assert body["madmom_error"] == reported
    for key in ("ffmpeg", "ffprobe"):
        assert isinstance(body[key], bool)


def test_health_with_a_really_broken_import(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    # the unpatched check, so the route, the cache and the message all line up
    installed(monkeypatch, True)
    fail_madmom_imports(monkeypatch, AttributeError("module 'numpy' has no attribute 'float'"))

    with TestClient(create_app(settings)) as client:
        body = client.get("/api/health").json()

    assert body["madmom"] is False
    assert body["madmom_error"] == NUMPY_ATTRIBUTE


def test_startup_tries_the_import_and_health_reuses_it(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    installed(monkeypatch, True)
    tried = fail_madmom_imports(monkeypatch, RuntimeError("boom"))
    assert tried == []

    with TestClient(create_app(settings)) as client:
        after_startup = len(tried)
        assert after_startup > 0
        for _ in range(3):
            assert client.get("/api/health").json()["madmom_error"] == "RuntimeError: boom"
        assert len(tried) == after_startup


# --- track_beats ---


def test_auto_falls_back_to_librosa_when_madmom_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("madmom shouldn't be called when it didn't import")

    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    monkeypatch.setattr(beats, "madmom_import_error", lambda: PKG_RESOURCES)
    monkeypatch.setattr(beats, "_track_madmom", must_not_run)
    track, trim = prepare()

    result = track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="auto")

    assert result.tracker == "librosa"
    assert not result.downbeats_known


def test_madmom_by_name_raises_with_the_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    monkeypatch.setattr(beats, "madmom_import_error", lambda: PKG_RESOURCES)
    track, trim = prepare()

    message = f"madmom is installed but doesn't import ({PKG_RESOURCES})"
    with pytest.raises(BeatTrackingError, match=re.escape(message)):
        track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="madmom")


def test_auto_uses_madmom_when_it_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    track, trim = prepare()
    times = trim.start_ms + 500.0 * np.arange(8)

    def fake_track(*_args, **_kwargs):
        return times, np.arange(8, dtype=np.int64) % 4 + 1

    monkeypatch.setattr(beats, "madmom_available", lambda: True)
    monkeypatch.setattr(beats, "madmom_import_error", lambda: None)
    monkeypatch.setattr(beats, "_track_madmom", fake_track)

    result = track_beats(track.samples, track.sample_rate, trim.start_ms, trim.end_ms, tracker="auto")

    assert result.tracker == "madmom"
    assert result.downbeats_known
    assert np.array_equal(result.times_ms, times)
