"""Small helpers for loading URL lists from plain-text files."""

from __future__ import annotations

import re
from pathlib import Path

from yt_subs.shared.models import UrlStr

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def load_urls_file(path: Path | str) -> list[UrlStr]:
    """Load URLs from a text file, one per line. Blank lines and # comments are skipped."""
    return [
        UrlStr(line.strip())
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def to_video_url(value: str) -> UrlStr:
    """
    Accept either a full URL or a bare YouTube video ID.

    ``youtube-transcript-api`` takes the 11-character ID, so ``fetch()``
    accepts both: anything with a scheme is passed through untouched, and a
    bare ID is turned into a watch URL. Anything else is passed through, so a
    URL without a scheme (``youtube.com/watch?v=...``) still works.
    """
    value = value.strip()
    if "://" in value or "." in value:
        return UrlStr(value)
    if _VIDEO_ID_RE.fullmatch(value):
        return UrlStr(f"https://www.youtube.com/watch?v={value}")
    return UrlStr(value)
