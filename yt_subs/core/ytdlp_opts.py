"""Shared yt-dlp option builders used by extractor and downloader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from yt_dlp.cookies import SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS

from yt_subs.error import YtSubsValueError
from yt_subs.shared.models import BrowserCookies, SubtitleFormat, VideoId

YOUTUBE_EXTRACTOR_ARGS: dict[str, dict[str, list[str]]] = {
    "youtube": {
        "skip": ["dash", "hls"],
        "player_client": ["android_vr"],
        "player_skip": ["configs", "js", "initial_data"],
    }
}

PROXY_SCHEMES = frozenset({"http", "https", "socks4", "socks4a", "socks5", "socks5h"})

# urllib can tunnel an https target through an http proxy (CONNECT), but it
# cannot speak SOCKS or TLS to the proxy itself. Other schemes are still valid
# for yt-dlp, which has its own networking stack.
DIRECT_FETCH_PROXY_SCHEMES = frozenset({"http"})

_COOKIE_SPEC_RE = re.compile(
    r"""(?x)
    (?P<browser>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)


def normalize_cookies(cookies: str | None) -> BrowserCookies | None:
    if not cookies:
        return None

    match_ = _COOKIE_SPEC_RE.fullmatch(cookies.strip())
    if match_ is None:
        raise YtSubsValueError(
            f"invalid cookies spec: {cookies!r}. Expected BROWSER[+KEYRING]"
            "[:PROFILE][::CONTAINER], e.g. 'chrome' or 'firefox:myprofile'."
        )

    browser = match_.group("browser").strip().lower()
    keyring = match_.group("keyring")
    profile = match_.group("profile")
    container = match_.group("container")

    if browser not in SUPPORTED_BROWSERS:
        raise YtSubsValueError(
            f"unsupported browser: {browser!r}. Supported browsers are: "
            f"{', '.join(sorted(SUPPORTED_BROWSERS))}."
        )
    if keyring is not None:
        keyring = keyring.strip().upper()
        if keyring not in SUPPORTED_KEYRINGS:
            raise YtSubsValueError(
                f"unsupported keyring: {keyring!r}. Supported keyrings are: "
                f"{', '.join(sorted(SUPPORTED_KEYRINGS))}."
            )

    return browser, profile, keyring, container


def normalize_cookiefile(cookiefile: Path | str | None) -> str | None:
    """Validate a Netscape cookies.txt path and return it as a string."""
    if cookiefile is None:
        return None

    path = Path(cookiefile).expanduser()
    if not path.is_file():
        raise YtSubsValueError(
            f"cookiefile does not exist or is not a file: {path}. "
            "Export cookies with a browser extension (Netscape format)."
        )
    return str(path)


def normalize_proxy(proxy: str | None) -> str | None:
    """Validate a proxy URL and return it unchanged."""
    if not proxy:
        return None

    parsed = urlsplit(proxy)
    if parsed.scheme not in PROXY_SCHEMES or not parsed.netloc:
        raise YtSubsValueError(
            f"invalid proxy: {proxy!r}. Expected scheme://host:port with scheme "
            f"one of {', '.join(sorted(PROXY_SCHEMES))}."
        )
    return proxy


def proxy_supports_direct_fetch(proxy: str | None) -> bool:
    """True when the direct urllib fetcher can use this proxy."""
    if not proxy:
        return True
    return urlsplit(proxy).scheme in DIRECT_FETCH_PROXY_SCHEMES


def require_direct_fetch_proxy(proxy: str | None) -> None:
    """Raise when ``fetch()`` was given a proxy urllib cannot use."""
    if not proxy_supports_direct_fetch(proxy):
        raise YtSubsValueError(
            f"fetch() downloads caption bytes directly and cannot use proxy "
            f"{proxy!r}; only http:// proxies are supported here. Use "
            f"download() for SOCKS or https:// proxies."
        )


def base_extract_opts(
    *,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Lightweight metadata extraction options."""
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        # yt-dlp's defaults are tuned for one interactive download and can sit
        # in backoff for a minute or more. A library must fail fast instead.
        "retries": 2,
        "extractor_retries": 1,
        "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
        **overrides,
    }
    if cookies is not None:
        opts["cookiesfrombrowser"] = cookies
    if cookiefile is not None:
        opts["cookiefile"] = cookiefile
    if proxy is not None:
        opts["proxy"] = proxy
    return opts


def subtitle_download_opts(
    *,
    output_dir: Path,
    video_id: VideoId,
    subtitle_format: SubtitleFormat,
    resolved_langs: list[str],
    skip_video: bool,
    sleep_interval_subtitles: int,
    sleep_interval_requests: int,
    quiet: bool = True,
    cookies: BrowserCookies | None = None,
    cookiefile: str | None = None,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Options for downloading subtitles (with or without video)."""
    opts: dict[str, Any] = {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [*dict.fromkeys(resolved_langs)],
        "subtitlesformat": subtitle_format,
        "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
        "skip_download": skip_video,
        "sleep_interval_subtitles": sleep_interval_subtitles,
        "sleep_interval_requests": sleep_interval_requests,
        "socket_timeout": 30,
        "retries": 2,
        "extractor_retries": 1,
        "extractor_args": YOUTUBE_EXTRACTOR_ARGS,
        "noprogress": True,
    }

    if cookies is not None:
        opts["cookiesfrombrowser"] = cookies
    if cookiefile is not None:
        opts["cookiefile"] = cookiefile
    if proxy is not None:
        opts["proxy"] = proxy

    if quiet:
        opts["quiet"] = True
        opts["no_warnings"] = True

    if not skip_video:
        opts["format"] = "worst[ext=mp4]/worst"

    return opts
