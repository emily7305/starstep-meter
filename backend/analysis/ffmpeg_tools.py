"""Finding and running ffmpeg / ffprobe."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class ToolNotFoundError(RuntimeError):
    pass


def find_tool(name: str) -> str | None:
    # shutil.which handles .exe on windows, so no special casing here
    return shutil.which(name)


def require_tool(name: str) -> str:
    path = find_tool(name)
    if path is None:
        raise ToolNotFoundError(f"{name} not found on PATH")
    return path


def run_tool(args: list[str], timeout_s: float = 600.0) -> subprocess.CompletedProcess[str]:
    # utf-8 with replace so a weird filename in stderr can't crash the job on windows (cp1252 default)
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        check=False,
    )


def last_error_line(stderr: str, path: Path | None = None) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    line = lines[-1] if lines else "no error output"
    # ffmpeg prefixes errors with the full path, which is just our job dir and means nothing in the ui
    if path is not None:
        line = line.replace(f"{path}: ", "").replace(str(path), path.name)
    return line
