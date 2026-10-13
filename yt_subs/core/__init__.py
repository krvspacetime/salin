"""
core/__init__.py

Public surface of the core package. Import from here rather than from
sub-modules so internal reorganisation doesn't break callers.
"""

from yt_subs.core.downloader import download_subtitles, find_subtitle_file
from yt_subs.core.extractor import (
    extract_info,
    inspect_subtitle_availability,
    inspect_subtitles,
    log_subtitle_availability,
)
from yt_subs.core.resolver import resolve_availability

__all__ = [
    "download_subtitles",
    "extract_info",
    "inspect_subtitle_availability",
    "find_subtitle_file",
    "inspect_subtitles",
    "log_subtitle_availability",
    "resolve_availability",
]
