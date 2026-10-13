"""
parsers/__init__.py

Registry mapping SubtitleFormat -> parser. Adding a format means adding one
entry here plus a module that returns ParsedCues.
"""

from __future__ import annotations

from pathlib import Path

from yt_subs.error import UnsupportedFormatError
from yt_subs.shared.models import SubtitleFormat

from .common import CueReader, ParsedCue, SourceParser, timestamp_to_ms
from .json3 import parse_json3_cues, read_json3_cues
from .srt import parse_srt_cues, read_srt_cues
from .srv import (
    parse_srv1_cues,
    parse_srv2_cues,
    parse_srv3_cues,
    read_srv1_cues,
    read_srv2_cues,
    read_srv3_cues,
)
from .ttml import parse_ttml_cues, read_ttml_cues
from .vtt import parse_vtt_cues, read_vtt_cues

CUE_READERS: dict[SubtitleFormat, CueReader] = {
    SubtitleFormat.SRT: read_srt_cues,
    SubtitleFormat.VTT: read_vtt_cues,
    SubtitleFormat.JSON3: read_json3_cues,
    SubtitleFormat.SRV1: read_srv1_cues,
    SubtitleFormat.SRV2: read_srv2_cues,
    SubtitleFormat.SRV3: read_srv3_cues,
    SubtitleFormat.TTML: read_ttml_cues,
}

SOURCE_PARSERS: dict[SubtitleFormat, SourceParser] = {
    SubtitleFormat.SRT: parse_srt_cues,
    SubtitleFormat.VTT: parse_vtt_cues,
    SubtitleFormat.JSON3: parse_json3_cues,
    SubtitleFormat.SRV1: parse_srv1_cues,
    SubtitleFormat.SRV2: parse_srv2_cues,
    SubtitleFormat.SRV3: parse_srv3_cues,
    SubtitleFormat.TTML: parse_ttml_cues,
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
    "SOURCE_PARSERS",
    "SUPPORTED_FORMATS",
    "CueReader",
    "SourceParser",
    "ParsedCue",
    "parse_json3_cues",
    "parse_srt_cues",
    "parse_srv1_cues",
    "parse_srv2_cues",
    "parse_srv3_cues",
    "parse_ttml_cues",
    "parse_vtt_cues",
    "read_blocks",
    "read_cues",
    "read_json3_cues",
    "read_srt_cues",
    "read_srv1_cues",
    "read_srv2_cues",
    "read_srv3_cues",
    "read_ttml_cues",
    "read_vtt_cues",
    "reader_for",
    "timestamp_to_ms",
]
