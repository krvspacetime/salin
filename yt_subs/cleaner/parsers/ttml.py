"""
ttml.py

TTML (Timed Text Markup Language), the W3C format YouTube also serves::

    <tt><body><div>
      <p begin="00:00:01.360" end="00:00:03.040" style="s2">...</p>
    </div></body></tt>

Timestamps are clock times rather than offsets, and a paragraph may give either
an ``end`` or a ``dur`` (``"3.5s"``). Lines break with ``<br />``, which the
shared normalizer turns into a space.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from yt_subs.cleaner.normalize import normalize_caption_text

from .common import ParsedCue, element_text, iter_local, timestamp_to_ms


def _offset_to_ms(value: str) -> int:
    """Accept both clock times (``00:00:01.360``) and offsets (``1.36s``)."""
    stripped = value.strip()
    if stripped.endswith("s"):
        return int(round(float(stripped[:-1]) * 1000))
    return timestamp_to_ms(stripped)


def parse_ttml_cues(source: str) -> list[ParsedCue]:
    root = ElementTree.fromstring(source)
    cues: list[ParsedCue] = []

    for node in iter_local(root, "p"):
        begin = node.get("begin")
        if begin is None:
            continue

        start_ms = _offset_to_ms(begin)

        end = node.get("end")
        if end is not None:
            end_ms = _offset_to_ms(end)
        else:
            dur = node.get("dur")
            end_ms = start_ms + (_offset_to_ms(dur) if dur else 0)

        text = normalize_caption_text(element_text(node))
        if text:
            cues.append(
                ParsedCue(
                    index=len(cues),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )

    return cues


def read_ttml_cues(path: Path) -> list[ParsedCue]:
    if not path.exists():
        raise FileNotFoundError(path)
    return parse_ttml_cues(path.read_text(encoding="utf-8-sig"))
