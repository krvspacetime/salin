"""
core/__init__.py

Public surface of the core package. Import from here rather than from
sub-modules so internal reorganisation doesn't break callers.
"""

from yt_subs.core.downloader import (
    download_subtitles,
    find_subtitle_file,
    find_track,
    find_track_url,
)
from yt_subs.core.extractor import (
    close_ydl_pool,
    extract_info,
    inspect_subtitle_availability,
    inspect_subtitles,
    log_subtitle_availability,
)
from yt_subs.core.fetcher import FetchedCues, fetch_transcript_cues
from yt_subs.core.resolver import resolve_availability

__all__ = [
    "close_ydl_pool",
    "download_subtitles",
    "extract_info",
    "fetch_transcript_cues",
    "FetchedCues",
    "find_subtitle_file",
    "find_track",
    "find_track_url",
    "inspect_subtitle_availability",
    "inspect_subtitles",
    "log_subtitle_availability",
    "resolve_availability",
]
