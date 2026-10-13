"""
srv.py

YouTube's own timed-text XML, in three flavours that differ in more than name:

- srv1  ``<transcript><text start="1.36" dur="1.68">``  -- seconds, as floats
- srv2  ``<timedtext><text t="1360" d="1680">``         -- milliseconds
- srv3  ``<timedtext format="3"><body><p t="1360" ...>`` -- milliseconds

srv1 and srv2 also escape ampersands twice (``&amp;#39;``), so their text needs
a second unescape pass after the XML parser has run.
"""

from __future__ import annotations

import html
from pathlib import Path
from xml.etree import ElementTree

from yt_subs.cleaner.normalize import normalize_caption_text

from .common import ParsedCue, element_text, iter_local


def _to_ms(value: str, *, divisor: float) -> int:
    return int(round(float(value) * divisor))


def _unescape(value: str) -> str:
    return normalize_caption_text(html.unescape(value))


def _build(
    root: ElementTree.Element, tag: str, key: str, divisor: float
) -> list[ParsedCue]:
    cues: list[ParsedCue] = []

    for node in iter_local(root, tag):
        start_raw = node.get(key)
        if start_raw is None:
            continue

        start_ms = _to_ms(start_raw, divisor=divisor)
        dur_raw = node.get("dur") or node.get("d")
        dur_ms = _to_ms(dur_raw, divisor=divisor) if dur_raw else 0

        text = _unescape(element_text(node))
        if text:
            cues.append(
                ParsedCue(
                    index=len(cues),
                    start_ms=start_ms,
                    end_ms=start_ms + dur_ms,
                    text=text,
                )
            )

    return cues


def parse_srv1_cues(source: str) -> list[ParsedCue]:
    return _build(ElementTree.fromstring(source), "text", "start", divisor=1000)


def parse_srv2_cues(source: str) -> list[ParsedCue]:
    return _build(ElementTree.fromstring(source), "text", "t", divisor=1)


def parse_srv3_cues(source: str) -> list[ParsedCue]:
    return _build(ElementTree.fromstring(source), "p", "t", divisor=1)


def _read(path: Path, parse) -> list[ParsedCue]:
    if not path.exists():
        raise FileNotFoundError(path)
    return parse(path.read_text(encoding="utf-8-sig"))


def read_srv1_cues(path: Path) -> list[ParsedCue]:
    return _read(path, parse_srv1_cues)


def read_srv2_cues(path: Path) -> list[ParsedCue]:
    return _read(path, parse_srv2_cues)


def read_srv3_cues(path: Path) -> list[ParsedCue]:
    return _read(path, parse_srv3_cues)
