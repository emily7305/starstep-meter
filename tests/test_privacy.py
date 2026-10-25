"""Nothing tracked may hold a local path or someone's email address.

Runs over `git ls-files`, so it skips outside a git checkout. With tests/real/SONGS.local.md
present (git-ignored, the owner's machine only), the search terms listed in it are checked too,
so the tracked files never have to name the songs themselves.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SONGS = ROOT / "tests" / "real" / "SONGS.local.md"

# this file has to spell them out, so it's the one file left out
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()

PATHS = re.compile(r"[A-Za-z]:\\Users\\|/home/|/Users/|/tmp/claude", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"(?:\d+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com|noreply@github\.com", re.IGNORECASE)


def _tracked() -> list[tuple[str, str]]:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    names = subprocess.run([git, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    out = []
    for raw in names:
        name = raw.decode("utf-8")
        if not name or name == SELF:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            out.append((name, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            # nothing binary is tracked on purpose, an empty __init__.py reads fine
            continue
    return out


def _hits(pattern: re.Pattern[str], allowed: re.Pattern[str] | None = None) -> list[str]:
    found = []
    for name, text in _tracked():
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in pattern.finditer(line):
                if allowed is not None and allowed.fullmatch(m.group(0)):
                    continue
                found.append(f"{name}:{lineno}: {m.group(0)}")
    return found


def test_no_local_paths_in_tracked_files():
    assert _hits(PATHS) == []


def test_no_email_addresses_but_noreply_ones():
    assert _hits(EMAIL, ALLOWED_EMAIL) == []


def _search_terms() -> list[str]:
    # one term per line under a "## search terms" heading, "- " in front
    terms, inside = [], False
    for line in SONGS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## search terms"
            continue
        if inside and line.startswith("- ") and line[2:].strip():
            terms.append(line[2:].strip())
    return terms


def test_no_real_song_names_in_tracked_files():
    if not SONGS.exists():
        pytest.skip("tests/real/SONGS.local.md is only on the owner's machine")
    terms = _search_terms()
    if not terms:
        pytest.skip("SONGS.local.md lists no search terms")
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    assert _hits(pattern) == []
