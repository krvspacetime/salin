"""Caption text normalization shared by the parsers and the deduplicator."""

from __future__ import annotations

import html
import re

_INLINE_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BROKEN_TAG_RE = re.compile(r"<[^>]*\s*$")
_MUSIC_CHAR_RE = re.compile(r"[\u266a\u266b\U0001f3b5\U0001f3b6]")

# Matches speaker chevrons (>> or >) preceded by start-of-string or whitespace
_SPEAKER_PREFIX_RE = re.compile(r"(?:^|\s)>{1,2}\s*")

_BRACKET_STAGE_RE = re.compile(
    r"\[(?:Music|Applause|Laughter|Silence|Inaudible|Crowd)[^\]]*\]",
    re.IGNORECASE,
)
_PAREN_STAGE_RE = re.compile(
    r"\((?:music|applause|laughter|inaudible|crowd noise)[^)]*\)",
    re.IGNORECASE,
)

# A cue that is only music symbols, e.g. "[♪♪♪]", matches neither stage pattern
# above because neither spells a keyword. The brackets survive the symbol
# removal and reach the transcript as a stray "[]".
_EMPTY_GROUP_RE = re.compile(r"\[\s*\]|\(\s*\)")


def strip_inline_markup(text: str) -> str:
    # <br> separates words, so it has to become a space before the generic tag
    # stripper removes it -- otherwise "rules<br />and" collapses to
    # "rulesand". TTML uses it; VTT and SRT use newlines instead.
    text = _BREAK_TAG_RE.sub(" ", text)
    text = _INLINE_TAG_RE.sub("", text)
    text = _BROKEN_TAG_RE.sub("", text)
    text = html.unescape(text)
    return " ".join(text.split())


def normalize_caption_text(text: str) -> str:
    """Remove stage directions and caption artifacts while keeping spoken words."""
    text = strip_inline_markup(text)
    text = _MUSIC_CHAR_RE.sub("", text)
    text = _EMPTY_GROUP_RE.sub("", text)

    # Replace chevrons with a space to prevent merging adjacent words,
    # then let the final split().join() clean up double spaces.
    text = _SPEAKER_PREFIX_RE.sub(" ", text)

    text = _BRACKET_STAGE_RE.sub("", text)
    text = _PAREN_STAGE_RE.sub("", text)
    return " ".join(text.split())
