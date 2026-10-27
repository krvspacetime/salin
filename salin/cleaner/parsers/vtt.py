import re
from pathlib import Path

from salin.cleaner.normalize import normalize_caption_text

from .common import ParsedCue

# The hours field is optional in WebVTT, and cue settings (align, position, ...)
# may follow the end timestamp.
_VTT_TIMESTAMP_RE = re.compile(
    r"(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})\s+-->\s+(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})"
)
_VTT_SKIP_PREFIXES = ("WEBVTT", "Kind:", "Language:", "Style:")


def _to_ms(hours: str | None, minutes: str, seconds: str, millis: str) -> int:
    total_ms = int(minutes) * 60_000 + int(seconds) * 1_000 + int(millis)
    return total_ms + (int(hours) * 3_600_000 if hours else 0)


def parse_vtt_cues(source: str) -> list[ParsedCue]:
    """Parse VTT source text into structured VTT ParsedCues."""
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

    for raw in source.splitlines():
        line = raw.strip()
        if not line or any(line.startswith(p) for p in _VTT_SKIP_PREFIXES):
            continue

        match = _VTT_TIMESTAMP_RE.search(line)
        if match:
            flush()
            start_ms = _to_ms(*match.group(1, 2, 3, 4))
            end_ms = _to_ms(*match.group(5, 6, 7, 8))
            continue

        current_lines.append(line)

    flush()
    return cues


def read_vtt_cues(path: Path) -> list[ParsedCue]:
    """Read a VTT file and return fully-resolved ParsedCues (including times)."""
    if not path.exists():
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8-sig") as f:
        return parse_vtt_cues(f.read())
