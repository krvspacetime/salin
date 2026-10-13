"""Turn downloaded caption files into readable, deduplicated plain text."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from yt_subs.cleaner.dedup import deduplicate_blocks
from yt_subs.cleaner.normalize import normalize_caption_text
from yt_subs.cleaner.parsers import read_cues
from yt_subs.shared.models import SubtitleFile, SubtitleFormat, SubtitleResult

log = logging.getLogger(__name__)


def clean_cues(path: Path, subtitle_format: SubtitleFormat) -> str:
    """
    Parse a subtitle file and return the cleaned transcript as a single string.

    Normalization runs before deduplication so stage directions like
    ``[Laughter]`` don't break the overlap detection matching.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    cues = read_cues(path, subtitle_format)
    blocks = [normalize_caption_text(cue.text) for cue in cues]
    return deduplicate_blocks(blocks)


def _clean_one(subtitle: SubtitleFile, out_path: Path | None) -> Path:
    if subtitle.sub_path is None:
        raise ValueError("subtitle path is required")
    if subtitle.format is None:
        raise ValueError("subtitle format is required")

    source = subtitle.sub_path
    txt_path = (
        out_path / source.with_suffix(".txt").name
        if out_path is not None
        else source.with_suffix(".txt")
    )

    transcript = clean_cues(source, subtitle.format)
    txt_path.write_text(transcript, encoding="utf-8")
    log.info("     ↳ clean transcript: %s", txt_path.name)
    return txt_path


def clean_transcript(
    transcript_result: SubtitleResult | Iterable[SubtitleFile],
    *,
    output_dir: Path | str | None = None,
    max_workers: int = 1,
) -> tuple[Path, ...]:
    """
    Clean every successfully downloaded subtitle in ``transcript_result``.

    Writes one ``.txt`` per subtitle. With ``output_dir`` set, the transcripts
    land there; otherwise they are written next to the source subtitle.

    Returns the paths written, in input order.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    out_path = Path(output_dir) if output_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    subtitles = (
        transcript_result.ok_subs
        if isinstance(transcript_result, SubtitleResult)
        else transcript_result
    )
    subtitle_list = [s for s in subtitles if s.sub_path is not None]
    if not subtitle_list:
        return ()

    if max_workers == 1 or len(subtitle_list) == 1:
        return tuple(_clean_one(subtitle, out_path) for subtitle in subtitle_list)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return tuple(
            executor.map(_clean_one, subtitle_list, [out_path] * len(subtitle_list))
        )
