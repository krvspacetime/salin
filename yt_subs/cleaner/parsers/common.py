"""Shared types for subtitle cue parsers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True, slots=True)
class ParsedCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


type CueReader = Callable[[Path], list[ParsedCue]]

# Every parse_*_cues function takes the file's full text, so callers can pick
# whichever form is convenient and the registry stays uniform.
type SourceParser = Callable[[str], list[ParsedCue]]


def timestamp_to_ms(value: str) -> int:
    """Converts a standard caption timestamp string (with , or .) into milliseconds."""
    normalized = value.strip().replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return int(total_seconds * 1000)


def iter_local(root: ElementTree.Element, name: str) -> Iterator[ElementTree.Element]:
    """
    Yield descendants whose tag is ``name``, ignoring any XML namespace.

    A namespaced document qualifies every tag as ``{uri}name``, so a plain
    ``root.iter("p")`` silently finds nothing in TTML, which is always served
    with ``xmlns="http://www.w3.org/ns/ttml"``.
    """
    for node in root.iter():
        if isinstance(node.tag, str) and node.tag.rpartition("}")[2] == name:
            yield node


def element_text(node: ElementTree.Element) -> str:
    """
    Flatten an element's full text content, turning ``<br>`` into a space.

    ``node.text`` alone stops at the first child, so for TTML
    ``<p>rules<br />and</p>`` would yield just "rules" and silently drop the
    rest of the cue.
    """
    parts: list[str] = [node.text or ""]

    for child in node:
        if isinstance(child.tag, str) and child.tag.rpartition("}")[2] == "br":
            parts.append(" ")
        else:
            parts.append(element_text(child))
        parts.append(child.tail or "")

    return "".join(parts)
