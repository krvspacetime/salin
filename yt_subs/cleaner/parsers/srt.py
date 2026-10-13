import re
from pathlib import Path

from yt_subs.cleaner.normalize import normalize_caption_text

from .common import ParsedCue, timestamp_to_ms

_SRT_TIMESTAMP_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})"
)
_SRT_SEQUENCE_RE = re.compile(r"^\d+$")


def parse_srt_cues(lines: list[str]) -> list[ParsedCue]:
    """Parse raw line lists into structured SRT ParsedCues."""
    cues: list[ParsedCue] = []
    current_lines: list[str] = []
    start_ms: int | None = None
    end_ms: int | None = None

    def flush() -> None:
        nonlocal start_ms, end_ms, current_lines
        if start_ms is None or end_ms is None:
            current_lines = []
            return

        # Merge lines and normalize them using the shared normalization logic
        text = normalize_caption_text(" ".join(current_lines)) if current_lines else ""
        if text:
            cues.append(
                ParsedCue(
                    index=len(cues),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                )
            )
        current_lines = []
        start_ms = None
        end_ms = None

    for raw in lines:
        line = raw.strip()
        if not line:
            flush()
            continue

        match = _SRT_TIMESTAMP_RE.search(line)
        if match:
            start_ms = timestamp_to_ms(match.group(1))
            end_ms = timestamp_to_ms(match.group(2))
            continue

        # A bare index only ever precedes a timestamp, so a digit-only line
        # before one is the sequence number. After a timestamp the same line is
        # real text -- a caption can legitimately be just "2024".
        if start_ms is None and _SRT_SEQUENCE_RE.match(line):
            continue

        current_lines.append(line)

    flush()
    return cues


def read_srt_cues(path: Path) -> list[ParsedCue]:
    """Read an SRT file and return fully-resolved ParsedCues (including times)."""
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8-sig") as f:
        return parse_srt_cues(f.readlines())
