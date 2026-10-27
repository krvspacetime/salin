"""
core/fetcher.py

Fetch caption cues in memory, with no temp file and no yt-dlp download.

This backs ``Salin.fetch()``. It reuses the same track lookup and byte
validation as the file-writing downloader, then parses the payload straight
into cues.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError

from salin.cleaner.parsers import SOURCE_PARSERS, ParsedCue
from salin.core.downloader import fetch_subtitle_bytes, find_track
from salin.core.ytdlp_opts import require_direct_fetch_proxy
from salin.error import (
    RateLimitedError,
    SubtitleDownloadError,
    TranscriptUnavailableError,
)
from salin.shared.models import (
    LangCodeResolved,
    SubtitleFormat,
    SubtitleSource,
    VideoId,
    YtdlpVideoInfo,
)

# json3 first: it is the format youtube-transcript-api parses, so cue
# boundaries and timings line up exactly. The rest are fallbacks for tracks
# that do not publish json3.
FETCH_FORMAT_PRIORITY: tuple[SubtitleFormat, ...] = (
    SubtitleFormat.JSON3,
    SubtitleFormat.SRV3,
    SubtitleFormat.SRV1,
    SubtitleFormat.SRV2,
    SubtitleFormat.TTML,
    SubtitleFormat.VTT,
)


@dataclass(frozen=True, slots=True)
class FetchedCues:
    """Parsed cues plus the metadata needed to build a transcript object."""

    cues: tuple[ParsedCue, ...]
    resolved: LangCodeResolved
    source: SubtitleSource
    subtitle_format: SubtitleFormat
    # yt-dlp carries YouTube's own track name ("English", "German (Germany)").
    language_name: str | None = None


def fetch_transcript_cues(
    info: YtdlpVideoInfo,
    *,
    resolved: LangCodeResolved,
    source: SubtitleSource,
    formats: tuple[SubtitleFormat, ...] = FETCH_FORMAT_PRIORITY,
    proxy: str | None = None,
) -> FetchedCues:
    """
    Download one resolved track and parse it into cues, in memory.

    Raises ``TranscriptUnavailableError`` when the track has no fetchable
    format, and ``SubtitleDownloadError`` when the fetch itself fails. Unlike
    ``download()`` there is no yt-dlp fallback: the bytes are needed in memory
    and a failed request has nothing to retry against.
    """
    require_direct_fetch_proxy(proxy)

    video_id = VideoId(info.get("id", "unknown"))

    for subtitle_format in formats:
        track = find_track(
            info,
            resolved=resolved,
            source=source,
            subtitle_format=subtitle_format,
        )
        if track is None:
            continue

        url = track.get("url")
        if not isinstance(url, str):
            continue

        try:
            payload = fetch_subtitle_bytes(
                url, subtitle_format=subtitle_format, proxy=proxy
            )
        except RateLimitedError as exc:
            raise RateLimitedError(
                f"could not fetch {subtitle_format} transcript for {video_id} "
                f"({resolved}): {exc}",
                retry_after=exc.retry_after,
                video_id=str(video_id),
            ) from exc
        except HTTPError as exc:
            # fetch() has no yt-dlp fallback, so surface the status instead of
            # leaking a urllib error.
            raise SubtitleDownloadError(
                f"could not fetch {subtitle_format} transcript for {video_id} "
                f"({resolved}): HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise SubtitleDownloadError(
                f"could not fetch {subtitle_format} transcript for {video_id} "
                f"({resolved}): {exc}"
            ) from exc

        text = payload.decode("utf-8-sig", errors="replace")
        cues = SOURCE_PARSERS[subtitle_format](text)
        name = track.get("name")
        return FetchedCues(
            cues=tuple(cues),
            resolved=resolved,
            source=source,
            subtitle_format=subtitle_format,
            language_name=name if isinstance(name, str) and name else None,
        )

    raise TranscriptUnavailableError(
        video_id,
        f"no fetchable {'/'.join(f.value for f in formats)} track for "
        f"{resolved!r} ({source}) in {video_id}",
    )
