"""Shared types for subtitle cue parsers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParsedCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


type CueReader = Callable[[Path], list[ParsedCue]]
type LineParser = Callable[[list[str]], list[ParsedCue]]


def timestamp_to_ms(value: str) -> int:
    """Converts a standard caption timestamp string (with , or .) into milliseconds."""
    normalized = value.strip().replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return int(total_seconds * 1000)
