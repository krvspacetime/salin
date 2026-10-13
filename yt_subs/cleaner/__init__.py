"""
cleaner/__init__.py

Public surface of the cleaner package. Import from here rather than from
sub-modules so internal reorganisation doesn't break callers.
"""

from yt_subs.cleaner.cleaner import clean_cues, clean_transcript
from yt_subs.cleaner.dedup import deduplicate_blocks, sanitize_word
from yt_subs.cleaner.normalize import normalize_caption_text, strip_inline_markup

__all__ = [
    "clean_cues",
    "clean_transcript",
    "deduplicate_blocks",
    "normalize_caption_text",
    "sanitize_word",
    "strip_inline_markup",
]
