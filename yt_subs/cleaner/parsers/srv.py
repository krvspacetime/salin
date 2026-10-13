"""
srv.py

YouTube's own timed-text XML, in three flavours that differ in more than name:

- srv1  ``<transcript><text start="1.36" dur="1.68">``  -- seconds, as floats
- srv2  ``<timedtext><text t="1360" d="1680">``         -- milliseconds
- srv3  ``<timedtext format="3"><body><p t="1360" ...>`` -- milliseconds

srv1 and srv2 also escape ampersands twice (``&amp;#39;``), so their text needs
a second unescape pass after the XML parser has run.

srv2 is the odd one out structurally: it is emitted word-by-word, with
``append="1"`` marking words that continue the caption line already open. Only
the elements *without* that flag are captions. See :func:`parse_srv2_cues`.
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
    """
    Parse srv2, which is word-by-word rather than one element per caption.

    Every element without ``append="1"`` opens a caption line; the ones that
    follow carry ``append="1"`` and belong to that same line. On a 72-minute
    video that is 2170 base elements against 15741 continuations -- the same
    2170 captions srv1 and srv3 carry directly. Reading each element as its own
    cue turns the whole transcript into single-word blocks, and deduplicating
    single-word blocks against the running tail silently deletes every genuine
    repetition ("of of", "the the", "and and").
    """
    root = ElementTree.fromstring(source)
    cues: list[ParsedCue] = []

    words: list[str] = []
    start_ms: int | None = None
    end_ms: int | None = None

    def flush() -> None:
        nonlocal words, start_ms, end_ms
        text = " ".join(word for word in words if word)
        if text and start_ms is not None:
            cues.append(
                ParsedCue(
                    index=len(cues),
                    start_ms=start_ms,
                    end_ms=end_ms if end_ms is not None else start_ms,
                    text=text,
                )
            )
        words = []
        start_ms = None
        end_ms = None

    for node in iter_local(root, "text"):
        raw_t = node.get("t")
        piece = _unescape(element_text(node))

        if node.get("append") == "1":
            if start_ms is None or raw_t is None:
                continue
            if piece:
                words.append(piece)
                end_ms = _to_ms(raw_t, divisor=1) + _to_ms(
                    node.get("d") or "0", divisor=1
                )
            continue

        flush()
        if raw_t is None:
            continue

        line_start_ms = _to_ms(raw_t, divisor=1)
        start_ms = line_start_ms
        end_ms = line_start_ms + _to_ms(node.get("d") or "0", divisor=1)
        if piece:
            words.append(piece)

    flush()
    return cues


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
