from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen

import yt_dlp

from yt_subs.core.extractor import extract_info, is_native_auto_caption_track
from yt_subs.core.ytdlp_opts import (
    proxy_supports_direct_fetch,
    subtitle_download_opts,
)
from yt_subs.shared.models import (
    DownloadStatus,
    ResolvedSubtitle,
    SubtitleFile,
    UrlStr,
    LangCodeResolved,
    SubtitleFormat,
    SubtitleSource,
    VideoId,
    YtdlpVideoInfo,
    BrowserCookies,
    SubtitleTrack,
)
from yt_subs.error import ExtractorError, RateLimitedError, SubtitleDownloadError

log = logging.getLogger(__name__)

_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; yt-subs/0.1)"

_MAX_SUBTITLE_BYTES = 5 * 1024 * 1024

# Bounded retries for transient failures. YouTube's rate limit is a hard
# 429 and is never retried here; only 5xx/connection errors are.
_FETCH_RETRIES = 2
_RETRY_BASE_SECONDS = 0.5
_RETRY_JITTER = 0.25

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_filename_component(value: object) -> str:
    component = _UNSAFE_FILENAME_CHARS.sub("_", str(value)).strip(".-")
    if not component or component.upper() in _WINDOWS_RESERVED_NAMES:
        return "unknown"
    return component


def find_subtitle_file(
    output_dir: Path,
    video_id: VideoId,
    lang: LangCodeResolved,
    subtitle_format: SubtitleFormat,
) -> Path | None:
    expected = expected_subtitle_path(output_dir, video_id, lang, subtitle_format)
    if expected.exists():
        return expected

    log.warning("expected subtitle not found: %s", expected)
    return None


def expected_subtitle_path(
    output_dir: Path,
    video_id: VideoId,
    lang: LangCodeResolved,
    subtitle_format: SubtitleFormat,
) -> Path:
    dest = output_dir / f"{video_id}.{lang}.{subtitle_format}"
    if dest.resolve().parent != output_dir.resolve():
        raise SubtitleDownloadError(
            f"refusing to write subtitle outside of {output_dir}: {video_id!r}"
        )
    return dest


def find_track(
    info: YtdlpVideoInfo,
    *,
    resolved: LangCodeResolved,
    source: SubtitleSource,
    subtitle_format: SubtitleFormat,
) -> SubtitleTrack | None:
    """Return the first matching track dict, or None.

    Prefer this over :func:`find_track_url` when the track's ``name`` is
    useful: yt-dlp carries YouTube's own display name (``"English"``,
    ``"German (Germany)"``) alongside the URL.
    """
    pool_key = "subtitles" if source == SubtitleSource.MANUAL else "automatic_captions"
    tracks: list[SubtitleTrack] = info.get(pool_key, {}).get(resolved, [])

    for track in tracks:
        if track.get("ext") != subtitle_format:
            continue
        if source == SubtitleSource.AUTO and not is_native_auto_caption_track(track):
            continue
        url = track.get("url")
        if isinstance(url, str) and url:
            return track

    return None


def find_track_url(
    info: YtdlpVideoInfo,
    *,
    resolved: LangCodeResolved,
    source: SubtitleSource,
    subtitle_format: SubtitleFormat,
) -> str | None:
    """Return the direct download URL for a resolved subtitle track, if known."""
    track = find_track(
        info, resolved=resolved, source=source, subtitle_format=subtitle_format
    )
    if track is None:
        return None
    url = track.get("url")
    return url if isinstance(url, str) else None


def _strip_bom(payload: bytes) -> bytes:
    return payload[3:] if payload.startswith(b"\xef\xbb\xbf") else payload


def _looks_like_subtitle(payload: bytes, subtitle_format: SubtitleFormat) -> bool:
    head = _strip_bom(payload).lstrip()[:32]
    match subtitle_format:
        case SubtitleFormat.VTT:
            return head.startswith(b"WEBVTT")
        case SubtitleFormat.JSON3:
            return head.startswith(b"{")
        case SubtitleFormat.SRV1 | SubtitleFormat.SRV2 | SubtitleFormat.SRV3:
            return head.startswith(b"<?xml")
        case SubtitleFormat.TTML:
            return head.startswith(b"<?xml") or head.startswith(b"<tt")
        case SubtitleFormat.SRT:
            return re.match(rb"\d{1,6}\s", head) is not None
    return True


def parse_retry_after(headers) -> int | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds."""
    if headers is None:
        return None

    try:
        raw = headers.get("Retry-After")
    except AttributeError:
        return None
    if not raw:
        return None

    raw = raw.strip()
    if raw.isdigit():
        return int(raw)

    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    return max(int((when - datetime.now(timezone.utc)).total_seconds()), 0)


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter, small enough to fail fast."""
    return _RETRY_BASE_SECONDS * (2**attempt) * (1 + random.random() * _RETRY_JITTER)


def _open(
    request: Request,
    *,
    proxy: str | None,
    timeout: int,
):
    if proxy is None:
        return urlopen(request, timeout=timeout)
    opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
    return opener.open(request, timeout=timeout)


def fetch_subtitle_bytes(
    url: str,
    *,
    subtitle_format: SubtitleFormat,
    timeout: int = 30,
    max_bytes: int = _MAX_SUBTITLE_BYTES,
    proxy: str | None = None,
    retries: int = _FETCH_RETRIES,
    refresh_url: Callable[[], str | None] | None = None,
) -> bytes:
    """
    Download one subtitle track over HTTP and return its bytes.

    Error policy, in the order it is applied:

    - ``429``: raise :class:`~yt_subs.error.RateLimitedError` immediately, with
      ``Retry-After`` when the server sent one. Never retried, never handed to
      yt-dlp: the endpoint is rate-limited, so retrying only makes it worse.
    - ``403``: signed track URLs expire. Call ``refresh_url`` once to get a
      fresh URL and retry; if that fails too, raise.
    - ``5xx`` and connection errors: retry a bounded number of times with
      jittered backoff, then raise.
    - Anything else, including a response that does not look like the requested
      format, raises :class:`~yt_subs.error.SubtitleDownloadError`.

    Shared by the file-writing downloader and the in-memory ``fetch()`` path.
    """
    if urlsplit(url).scheme not in ("http", "https"):
        raise SubtitleDownloadError(f"refusing to fetch non-http subtitle url: {url!r}")

    refreshed = False
    attempt = 0

    while True:
        request = Request(url, headers={"User-Agent": _FETCH_USER_AGENT})
        try:
            with _open(request, proxy=proxy, timeout=timeout) as response:
                payload = response.read(max_bytes + 1)
        except HTTPError as exc:
            if exc.code == 429:
                raise RateLimitedError(
                    f"YouTube rate-limited the {subtitle_format} caption "
                    f"request (HTTP 429)",
                    retry_after=parse_retry_after(exc.headers),
                ) from exc
            if exc.code == 403 and refresh_url is not None and not refreshed:
                refreshed = True
                fresh = refresh_url()
                if fresh:
                    log.info("  signed subtitle URL expired; re-extracted it")
                    url = fresh
                    continue
                raise
            if 500 <= exc.code < 600 and attempt < retries:
                delay = _retry_delay(attempt)
                log.warning(
                    "  caption server error %d; retrying in %.1fs", exc.code, delay
                )
                time.sleep(delay)
                attempt += 1
                continue
            raise
        except (URLError, TimeoutError) as exc:
            if attempt < retries:
                delay = _retry_delay(attempt)
                log.warning(
                    "  caption fetch failed (%s); retrying in %.1fs", exc, delay
                )
                time.sleep(delay)
                attempt += 1
                continue
            raise
        break

    if len(payload) > max_bytes:
        raise SubtitleDownloadError(
            f"subtitle response too large: over {max_bytes} bytes"
        )
    if payload.strip() and not _looks_like_subtitle(payload, subtitle_format):
        raise SubtitleDownloadError(
            f"subtitle response does not look like {subtitle_format}"
        )
    return payload


def _subtitle_file_from_path(
    item: ResolvedSubtitle,
    sub_path: Path,
    subtitle_format: SubtitleFormat,
) -> SubtitleFile:
    return SubtitleFile(
        requested=item.requested,
        resolved=item.resolved,
        source=item.source,
        status=DownloadStatus.OK,
        sub_path=sub_path,
        format=subtitle_format,
    )


def _missing_subtitle_file(item: ResolvedSubtitle) -> SubtitleFile:
    return SubtitleFile(
        requested=item.requested,
        resolved=item.resolved,
        source=item.source,
        status=DownloadStatus.MISSING,
    )


def _error_subtitle_file(item: ResolvedSubtitle, error: str) -> SubtitleFile:
    return SubtitleFile(
        requested=item.requested,
        resolved=item.resolved,
        source=item.source,
        status=DownloadStatus.ERROR,
        error=error,
    )


def _rate_limited_subtitle_file(
    item: ResolvedSubtitle,
    error: str,
    retry_after: int | None = None,
) -> SubtitleFile:
    return SubtitleFile(
        requested=item.requested,
        resolved=item.resolved,
        source=item.source,
        status=DownloadStatus.RATE_LIMITED,
        error=error,
        retry_after=retry_after,
    )


_RATE_LIMIT_NEEDLES = ("http error 429", "too many requests", "rate limit")


def looks_rate_limited(message: str) -> bool:
    """Best-effort 429 detection for errors that come back as plain strings."""
    lowered = message.lower()
    return any(needle in lowered for needle in _RATE_LIMIT_NEEDLES)


def _failed_subtitle_file(item: ResolvedSubtitle, error: str) -> SubtitleFile:
    """Classify a string error, which is how yt-dlp reports its failures."""
    if looks_rate_limited(error):
        return _rate_limited_subtitle_file(item, error)
    return _error_subtitle_file(item, error)


def _require_resolved(item: ResolvedSubtitle) -> LangCodeResolved:
    if item.resolved is None:
        raise SubtitleDownloadError(
            f"cannot download unresolved subtitle track: requested={item.requested!r}"
        )
    return item.resolved


def _require_source(item: ResolvedSubtitle) -> SubtitleSource:
    if item.source is None:
        raise SubtitleDownloadError(
            "cannot download subtitle track without a source: "
            f"requested={item.requested!r}"
        )
    return item.source


def _relabeled(file: SubtitleFile, item: ResolvedSubtitle) -> SubtitleFile:
    if file.requested == item.requested and file.source == item.source:
        return file
    return replace(file, requested=item.requested, source=item.source)


def _download_subtitles_direct(
    info: YtdlpVideoInfo,
    *,
    resolved_langs: tuple[ResolvedSubtitle, ...],
    video_id: VideoId,
    output_dir: Path,
    subtitle_format: SubtitleFormat,
    sleep_interval_subtitles: int,
    url: UrlStr | None = None,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
) -> tuple[dict[LangCodeResolved, SubtitleFile], tuple[ResolvedSubtitle, ...]]:
    """Fetch subtitle files over HTTP using URLs from pre-extracted metadata."""
    results: dict[LangCodeResolved, SubtitleFile] = {}

    if not proxy_supports_direct_fetch(proxy):
        # urllib cannot speak SOCKS or TLS-to-proxy; let yt-dlp do the whole
        # request instead of failing every language and retrying.
        log.info(
            "  proxy %r is not usable by the direct fetcher; using yt-dlp",
            proxy,
        )
        return results, resolved_langs

    fallback_items: list[ResolvedSubtitle] = []
    handled: set[LangCodeResolved] = set()

    for index, item in enumerate(resolved_langs):
        resolved = _require_resolved(item)
        source = _require_source(item)
        if resolved in handled:
            continue
        handled.add(resolved)
        if index > 0 and sleep_interval_subtitles > 0:
            time.sleep(sleep_interval_subtitles)

        dest = expected_subtitle_path(output_dir, video_id, resolved, subtitle_format)
        track_url = find_track_url(
            info,
            resolved=resolved,
            source=source,
            subtitle_format=subtitle_format,
        )

        if track_url is None:
            log.warning(
                "  no direct URL for '%s' (%s, %s)",
                item.requested,
                resolved,
                source,
            )
            fallback_items.append(item)
            continue

        def refresh_track_url(
            resolved: LangCodeResolved = resolved,
            source: SubtitleSource = source,
        ) -> str | None:
            # The only reason to re-extract is a signed URL that expired (403),
            # which happens when a batch reuses cached metadata.
            if url is None:
                return None
            try:
                fresh = extract_info(
                    url, cookies=cookies, cookiefile=cookiefile, proxy=proxy
                )
            except ExtractorError as exc:
                log.warning("  could not re-extract metadata: %s", exc)
                return None
            return find_track_url(
                fresh,
                resolved=resolved,
                source=source,
                subtitle_format=subtitle_format,
            )

        try:
            payload = fetch_subtitle_bytes(
                track_url,
                subtitle_format=subtitle_format,
                proxy=proxy,
                refresh_url=refresh_track_url,
            )
            if not payload.strip():
                log.warning(
                    "  empty response for '%s' (%s)",
                    item.requested,
                    resolved,
                )
                fallback_items.append(item)
                continue

            dest.write_bytes(payload)
            results[resolved] = _subtitle_file_from_path(item, dest, subtitle_format)
        except RateLimitedError as exc:
            # Do not hand this to yt-dlp: it would retry the same limited
            # endpoint with long, silent backoff.
            log.warning(
                "  rate limited on '%s' (%s): %s", item.requested, resolved, exc
            )
            results[resolved] = _rate_limited_subtitle_file(
                item, str(exc), exc.retry_after
            )
        except SubtitleDownloadError as exc:
            log.warning(
                "  rejected subtitle response for '%s' (%s): %s",
                item.requested,
                resolved,
                exc,
            )
            fallback_items.append(item)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            log.warning(
                "  direct fetch failed for '%s' (%s): %s",
                item.requested,
                resolved,
                exc,
            )
            fallback_items.append(item)

    return results, tuple(fallback_items)


def _download_subtitles_ytdlp(
    url: UrlStr,
    *,
    info: YtdlpVideoInfo | None,
    resolved_langs: tuple[ResolvedSubtitle, ...],
    video_id: VideoId,
    output_dir: Path,
    subtitle_format: SubtitleFormat,
    sleep_interval_subtitles: int,
    sleep_interval_requests: int,
    skip_video: bool,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
) -> str | None:
    """Download subtitles via yt-dlp. Reuses pre-extracted info when provided."""
    opts = subtitle_download_opts(
        output_dir=output_dir,
        video_id=video_id,
        subtitle_format=subtitle_format,
        resolved_langs=[
            item.resolved for item in resolved_langs if item.resolved is not None
        ],
        skip_video=skip_video,
        sleep_interval_subtitles=sleep_interval_subtitles,
        sleep_interval_requests=sleep_interval_requests,
        cookies=cookies,
        cookiefile=cookiefile,
        proxy=proxy,
    )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if info is not None:
                ydl.process_ie_result(info, download=True)
            else:
                ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        log.error("yt-dlp download error: %s", exc)
        return str(exc)

    return None


def _collect_results_after_ytdlp(
    resolved_langs: tuple[ResolvedSubtitle, ...],
    *,
    video_id: VideoId,
    output_dir: Path,
    subtitle_format: SubtitleFormat,
    error: str | None,
) -> tuple[SubtitleFile, ...]:
    files: list[SubtitleFile] = []
    for item in resolved_langs:
        resolved = _require_resolved(item)
        if error is not None:
            files.append(_failed_subtitle_file(item, error))
            continue

        sub_path = find_subtitle_file(output_dir, video_id, resolved, subtitle_format)
        if sub_path is None:
            log.warning(
                "  '%s' (%s) — .%s not found after download",
                item.requested,
                resolved,
                subtitle_format,
            )
            files.append(_missing_subtitle_file(item))
            continue

        files.append(_subtitle_file_from_path(item, sub_path, subtitle_format))

    return tuple(files)


def download_subtitles(
    url: UrlStr,
    *,
    resolved_langs: tuple[ResolvedSubtitle, ...],
    video_id: VideoId,
    output_dir: Path,
    subtitle_format: SubtitleFormat,
    sleep_interval_subtitles: int,
    sleep_interval_requests: int,
    skip_video: bool,
    info: YtdlpVideoInfo | None = None,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
) -> tuple[SubtitleFile, ...]:
    if not resolved_langs:
        return ()

    output_dir.mkdir(parents=True, exist_ok=True)

    safe_video_id = VideoId(safe_filename_component(video_id))

    log.info(
        "Downloading subtitles: %s",
        ", ".join(
            f"{item.requested}→{item.resolved}"
            if item.requested != item.resolved
            else str(item.requested)
            for item in resolved_langs
        ),
    )

    if info is not None and skip_video:
        direct_results, fallback_items = _download_subtitles_direct(
            info,
            resolved_langs=resolved_langs,
            video_id=safe_video_id,
            output_dir=output_dir,
            subtitle_format=subtitle_format,
            sleep_interval_subtitles=sleep_interval_subtitles,
            url=url,
            cookies=cookies,
            cookiefile=cookiefile,
            proxy=proxy,
        )

        if fallback_items:
            log.info(
                "Falling back to yt-dlp for %d subtitle(s)",
                len(fallback_items),
            )
            ytdlp_error = _download_subtitles_ytdlp(
                url,
                info=info,
                resolved_langs=fallback_items,
                video_id=safe_video_id,
                output_dir=output_dir,
                subtitle_format=subtitle_format,
                sleep_interval_subtitles=sleep_interval_subtitles,
                sleep_interval_requests=sleep_interval_requests,
                skip_video=True,
                cookies=cookies,
                cookiefile=cookiefile,
                proxy=proxy,
            )

            for item in fallback_items:
                resolved = _require_resolved(item)
                if ytdlp_error is not None:
                    direct_results[resolved] = _failed_subtitle_file(item, ytdlp_error)
                    continue

                sub_path = find_subtitle_file(
                    output_dir, safe_video_id, resolved, subtitle_format
                )
                if sub_path is None:
                    direct_results[resolved] = _missing_subtitle_file(item)
                else:
                    direct_results[resolved] = _subtitle_file_from_path(
                        item, sub_path, subtitle_format
                    )

        return tuple(
            _relabeled(direct_results[_require_resolved(item)], item)
            for item in resolved_langs
        )

    ytdlp_error = _download_subtitles_ytdlp(
        url,
        info=info,
        resolved_langs=resolved_langs,
        video_id=safe_video_id,
        output_dir=output_dir,
        subtitle_format=subtitle_format,
        sleep_interval_subtitles=sleep_interval_subtitles,
        sleep_interval_requests=sleep_interval_requests,
        skip_video=skip_video,
        cookies=cookies,
        cookiefile=cookiefile,
        proxy=proxy,
    )
    return _collect_results_after_ytdlp(
        resolved_langs,
        video_id=safe_video_id,
        output_dir=output_dir,
        subtitle_format=subtitle_format,
        error=ytdlp_error,
    )
