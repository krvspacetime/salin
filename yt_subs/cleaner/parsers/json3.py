"""
json3.py

YouTube's JSON caption format. Structured rather than rolling, so the cues come
out already separated -- no cue-boundary heuristics needed::

    {"events": [{"tStartMs": 1360, "dDurationMs": 1680,
                 "segs": [{"utf8": "..."}]}]}

Events with no ``segs`` are gaps between captions and carry no text; ``segs``
entries hold contiguous chunks of one line, so they join without a separator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yt_subs.cleaner.normalize import normalize_caption_text

from .common import ParsedCue


def parse_json3_cues(source: str) -> list[ParsedCue]:
    payload: Any = json.loads(source)
    if not isinstance(payload, dict):
        raise ValueError("json3 payload must be a JSON object")

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("json3 payload has no 'events' list")

    cues: list[ParsedCue] = []

    for event in events:
        if not isinstance(event, dict):
            continue

        start = event.get("tStartMs")
        if not isinstance(start, int):
            continue

        segs = event.get("segs")
        if not isinstance(segs, list):
            continue

        text = normalize_caption_text(
            "".join(
                seg["utf8"] for seg in segs if isinstance(seg, dict) and seg.get("utf8")
            )
        )
        if not text:
            continue

        duration = event.get("dDurationMs")
        cues.append(
            ParsedCue(
                index=len(cues),
                start_ms=start,
                end_ms=start + (duration if isinstance(duration, int) else 0),
                text=text,
            )
        )

    return cues


def read_json3_cues(path: Path) -> list[ParsedCue]:
    if not path.exists():
        raise FileNotFoundError(path)
    return parse_json3_cues(path.read_text(encoding="utf-8-sig"))
