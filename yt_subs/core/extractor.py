"""
core/extractor.py

Thin wrappers around yt-dlp's metadata extraction.
No download happens here — pure inspection.
"""

from __future__ import annotations

import atexit
import logging
import threading
from urllib.parse import parse_qs, urlparse

import yt_dlp

from yt_subs.core.ytdlp_opts import base_extract_opts
from yt_subs.error import ExtractorError, VideoUnavailableError
from yt_subs.shared.models import (
    BrowserCookies,
    LangCode,
    LangCodeAuto,
    LangCodeManual,
    LangCodeRequested,
    SubtitleAvailability,
    SubtitleTrack,
    UrlStr,
    VideoId,
    YtdlpVideoInfo,
)

log = logging.getLogger(__name__)

# Constructing a YoutubeDL is expensive -- it validates options, builds the
# request handler and registers every extractor, roughly 0.3s per call -- and
# that cost is paid once per video even though callers usually extract one
# video at a time in a loop. Keep one instance per thread and per request-option
# triple so repeated extracts reuse the setup instead of rebuilding it.
_YdlKey = tuple[BrowserCookies | None, str | None, str | None]
_ydl_local = threading.local()


def _ydl_cache() -> dict[_YdlKey, yt_dlp.YoutubeDL]:
    cache = getattr(_ydl_local, "cache", None)
    if cache is None:
        cache = {}
        _ydl_local.cache = cache
    return cache


def _get_ydl(
    cookies: BrowserCookies | None,
    cookiefile: str | None,
    proxy: str | None,
) -> yt_dlp.YoutubeDL:
    key: _YdlKey = (cookies, cookiefile, proxy)
    cache = _ydl_cache()
    ydl = cache.get(key)
    if ydl is None:
        opts = base_extract_opts(cookies=cookies, cookiefile=cookiefile, proxy=proxy)
        ydl = yt_dlp.YoutubeDL(opts)
        cache[key] = ydl
    return ydl


def close_ydl_pool() -> None:
    """
    Close and forget this thread's cached :class:`YoutubeDL` instances.

    The pool is keyed by request options, so it never needs clearing just
    because configuration changed; call this to release the instances early
    (for example before a process forks or during teardown).
    """
    cache = getattr(_ydl_local, "cache", None)
    if not cache:
        return
    for ydl in cache.values():
        close = getattr(ydl, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - best-effort teardown
                log.debug("Failed to close a pooled YoutubeDL", exc_info=True)
    cache.clear()


atexit.register(close_ydl_pool)


def is_native_auto_caption_track(track: SubtitleTrack) -> bool:
    """Return True for real auto-caption tracks, excluding translated variants."""
    url = track.get("url")
    if not isinstance(url, str):
        return False

    query = parse_qs(urlparse(url).query)
    return "tlang" not in query


def extract_info(
    url: UrlStr,
    *,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
) -> YtdlpVideoInfo:
    """
    Fetch video metadata without downloading anything.

    ``cookies``/``cookiefile``/``proxy`` are needed for age-restricted,
    region-locked, or bot-checked videos; pass them whenever the same request
    will later download subtitle bytes, or the signed track URLs from an
    anonymous extraction may not be usable.
    """
    try:
        ydl = _get_ydl(cookies, cookiefile, proxy)
        info = ydl.extract_info(url, download=False)
        return info
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if any(
            w in msg.lower()
            for w in (
                "private",
                "unavailable",
                "delete",
                "remove",
                "not exist",
                "sign in",
            )
        ):
            raise VideoUnavailableError(f"Video is unavailable: {url} ({msg})") from exc
        raise ExtractorError(f"Failed to extract video info for {url}: {msg}") from exc
    except Exception as exc:
        raise ExtractorError(
            f"Unexpected error extracting video info for {url}: {exc}"
        ) from exc


def inspect_subtitles(
    info: YtdlpVideoInfo,
) -> tuple[set[LangCodeManual], set[LangCodeAuto]]:
    manual = info.get("subtitles", {})
    auto = info.get("automatic_captions", {})

    native_auto_langs = {
        LangCode(lang)
        for lang, tracks in auto.items()
        if any(
            t.get("ext") == "vtt" and is_native_auto_caption_track(t) for t in tracks
        )
    }

    manual_langs = {LangCode(lang) for lang in manual}

    return manual_langs, native_auto_langs


def inspect_subtitle_availability(
    url: UrlStr,
    info: YtdlpVideoInfo,
) -> SubtitleAvailability:
    manual = info.get("subtitles", {})
    auto = info.get("automatic_captions", {})
    manual_langs, auto_langs = inspect_subtitles(info)

    manual_formats = {
        LangCode(lang): frozenset(
            t["ext"] for t in tracks if isinstance(t.get("ext"), str)
        )
        for lang, tracks in manual.items()
    }
    auto_formats = {
        LangCode(lang): frozenset(
            t["ext"]
            for t in tracks
            if isinstance(t.get("ext"), str) and is_native_auto_caption_track(t)
        )
        for lang, tracks in auto.items()
        if lang in auto_langs
    }

    return SubtitleAvailability(
        url=url,
        video_id=VideoId(info.get("id", "unknown")),
        title=str(info.get("title", "")),
        manual=frozenset(manual_langs),
        auto=frozenset(auto_langs),
        manual_formats=manual_formats,
        auto_formats=auto_formats,
    )


def log_subtitle_availability(
    availability: SubtitleAvailability,
    *,
    relevant_to: tuple[LangCodeRequested, ...] = (),
) -> None:
    """Log the availability of manual and automatic subtitles in the standard format."""

    def format_line(lang: str, is_manual: bool) -> str:
        source = "manual" if is_manual else "auto"
        format_map = (
            availability.manual_formats if is_manual else availability.auto_formats
        )
        exts_set = format_map.get(LangCode(lang), frozenset())
        exts_str = ", ".join(sorted(exts_set)) if exts_set else "unknown"
        return f"  {lang:<10} {source:<8} {exts_str}"

    if not relevant_to:
        if availability.manual or availability.auto:
            log.info("Available subtitles:")
            for lang in sorted(availability.manual):
                log.info(format_line(lang, is_manual=True))
            for lang in sorted(availability.auto):
                log.info(format_line(lang, is_manual=False))
        else:
            log.info("No subtitles available.")
    else:
        relevant_manual = sorted(
            lang for lang in availability.manual if lang in relevant_to
        )
        relevant_auto = sorted(
            lang for lang in availability.auto if lang in relevant_to
        )

        if relevant_manual or relevant_auto:
            log.info("Relevant subtitles:")
            for lang in relevant_manual:
                log.info(format_line(lang, is_manual=True))
            for lang in relevant_auto:
                log.info(format_line(lang, is_manual=False))
        else:
            log.info("No relevant subtitles found.")
