"""
parsers/__init__.py

Registry mapping SubtitleFormat -> parser. Adding a format means adding one
entry here plus a module that returns ParsedCues.
"""

from __future__ import annotations

from pathlib import Path

from yt_subs.error import UnsupportedFormatError
from yt_subs.shared.models import SubtitleFormat

from .common import CueReader, LineParser, ParsedCue, timestamp_to_ms
from .srt import parse_srt_cues, read_srt_cues
from .vtt import parse_vtt_cues, read_vtt_cues

CUE_READERS: dict[SubtitleFormat, CueReader] = {
    SubtitleFormat.SRT: read_srt_cues,
    SubtitleFormat.VTT: read_vtt_cues,
}

LINE_PARSERS: dict[SubtitleFormat, LineParser] = {
    SubtitleFormat.SRT: parse_srt_cues,
    SubtitleFormat.VTT: parse_vtt_cues,
}

SUPPORTED_FORMATS = tuple(CUE_READERS)


def reader_for(subtitle_format: SubtitleFormat) -> CueReader:
    reader = CUE_READERS.get(subtitle_format)
    if reader is None:
        supported = ", ".join(f"'{f}'" for f in SUPPORTED_FORMATS)
        raise UnsupportedFormatError(
            f"No subtitle parser for format '{subtitle_format}'. Supported: {supported}"
        )
    return reader


def read_cues(path: Path, subtitle_format: SubtitleFormat) -> list[ParsedCue]:
    """Read a subtitle file into fully-resolved cues."""
    return reader_for(subtitle_format)(path)


def read_blocks(path: Path, subtitle_format: SubtitleFormat) -> list[str]:
    """Read a subtitle file into text blocks, one per cue."""
    return [cue.text for cue in read_cues(path, subtitle_format)]


__all__ = [
    "CUE_READERS",
    "LINE_PARSERS",
    "SUPPORTED_FORMATS",
    "CueReader",
    "LineParser",
    "ParsedCue",
    "parse_srt_cues",
    "parse_vtt_cues",
    "read_blocks",
    "read_cues",
    "read_srt_cues",
    "read_vtt_cues",
    "reader_for",
    "timestamp_to_ms",
]
