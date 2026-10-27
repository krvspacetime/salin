"""
transcript.py

In-memory transcript objects shaped like ``youtube_transcript_api``'s.

``YtSubs.fetch()`` returns a :class:`FetchedTranscript`: an iterable of
:class:`TranscriptSnippet` plus the video and language metadata. The field
names and access patterns mirror ``youtube_transcript_api`` so existing code
usually needs only the import line changed.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class TranscriptSnippet:
    """One caption cue. ``start``/``duration`` are in seconds."""

    text: str
    start: float
    duration: float


@dataclass(frozen=True, slots=True)
class FetchedTranscript:
    """
    A fetched transcript, iterable over its snippets.

    Mirrors ``youtube_transcript_api.FetchedTranscript``. ``language`` is
    YouTube's own display name for the track when yt-dlp provides it, else the
    resolved language code; ``language_code`` is always the resolved code
    (``"en"``, ``"de-DE"``, ``"en-orig"``).
    """

    snippets: Sequence[TranscriptSnippet]
    video_id: str
    language: str
    language_code: str
    is_generated: bool

    def __iter__(self) -> Iterator[TranscriptSnippet]:
        return iter(self.snippets)

    def __getitem__(self, index: int) -> TranscriptSnippet:
        return self.snippets[index]

    def __len__(self) -> int:
        return len(self.snippets)

    def to_raw_data(self) -> list[dict]:
        """The snippets as plain dicts, same shape as youtube-transcript-api."""
        return [asdict(snippet) for snippet in self]

    @property
    def text(self) -> str:
        """
        All snippets joined with a single space.

        This is the raw caption text, not the deduplicated prose that
        ``clean_transcript()`` writes: JSON3 cues do not overlap, so there is
        nothing to collapse.
        """
        return " ".join(snippet.text for snippet in self)
