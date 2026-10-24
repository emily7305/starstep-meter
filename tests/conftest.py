import shutil

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "ffmpeg: needs ffmpeg and ffprobe on PATH")


def pytest_runtest_setup(item: pytest.Item) -> None:
    # skip, don't fail, so the pure-python tests still run on a machine without ffmpeg
    if item.get_closest_marker("ffmpeg"):
        for tool in ("ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                pytest.skip(f"{tool} not found on PATH")
