from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from tests.fixtures import MOCK_VIDEO_INFO_OK
from yt_subs import RateLimitedError, YtSubs
from yt_subs.core import downloader
from yt_subs.core.downloader import (
    download_subtitles,
    looks_rate_limited,
    parse_retry_after,
)
from yt_subs.error import SubtitleDownloadError
from yt_subs.shared.models import (
    DownloadStatus,
    LangCodeRequested,
    LangCodeResolved,
    ResolvedSubtitle,
    SubtitleFile,
    SubtitleFormat,
    SubtitleSource,
    UrlStr,
    VideoId,
    YtdlpVideoInfo,
)

VTT_URL = "https://example.com/en.vtt"
VTT_BODY = b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(VTT_URL, code, "err", headers, None)


# --- Retry-After parsing -------------------------------------------------


def test_parse_retry_after_delta_seconds():
    headers = Message()
    headers["Retry-After"] = " 42 "
    assert parse_retry_after(headers) == 42


def test_parse_retry_after_http_date():
    headers = Message()
    headers["Retry-After"] = format_datetime(datetime.now(UTC) + timedelta(seconds=60))
    value = parse_retry_after(headers)
    assert value is not None
    assert 55 <= value <= 60


def test_parse_retry_after_missing_or_garbage():
    assert parse_retry_after(None) is None
    assert parse_retry_after(Message()) is None

    headers = Message()
    headers["Retry-After"] = "soon"
    assert parse_retry_after(headers) is None


# --- HTTP policy ---------------------------------------------------------


def test_429_raises_rate_limited_with_retry_after(monkeypatch):
    attempts = []

    def fake_urlopen(request, timeout=None):
        attempts.append(request.full_url)
        raise _http_error(429, retry_after="30")

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)

    with pytest.raises(RateLimitedError) as excinfo:
        downloader.fetch_subtitle_bytes(VTT_URL, subtitle_format=SubtitleFormat.VTT)

    assert excinfo.value.retry_after == 30
    # A rate limit is never retried: one request, then fail.
    assert len(attempts) == 1


def test_429_is_not_handed_to_ytdlp(monkeypatch, tmp_path):
    fallback_calls = []

    monkeypatch.setattr(
        "yt_subs.core.downloader._download_subtitles_ytdlp",
        lambda *a, **k: fallback_calls.append(k),
    )
    monkeypatch.setattr(
        downloader,
        "fetch_subtitle_bytes",
        lambda *a, **k: (_ for _ in ()).throw(
            RateLimitedError("HTTP 429", retry_after=17)
        ),
    )

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": VTT_URL}]},
    }

    files = download_subtitles(
        UrlStr("https://www.youtube.com/watch?v=x"),
        resolved_langs=_resolved(),
        video_id=VideoId("abc123"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
    )

    assert files[0].status == DownloadStatus.RATE_LIMITED
    assert files[0].retry_after == 17
    assert "429" in (files[0].error or "")
    assert fallback_calls == []


def test_403_refreshes_the_signed_url_once(monkeypatch):
    requested = []

    def fake_urlopen(request, timeout=None):
        requested.append(request.full_url)
        if request.full_url == VTT_URL:
            raise _http_error(403)
        return _FakeResponse(VTT_BODY)

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)

    refreshes = []

    def refresh():
        refreshes.append(True)
        return "https://example.com/fresh.vtt"

    payload = downloader.fetch_subtitle_bytes(
        VTT_URL, subtitle_format=SubtitleFormat.VTT, refresh_url=refresh
    )

    assert payload == VTT_BODY
    assert requested == [VTT_URL, "https://example.com/fresh.vtt"]
    assert refreshes == [True]


def test_403_without_refresh_raises(monkeypatch):
    monkeypatch.setattr(
        downloader,
        "urlopen",
        lambda request, timeout=None: (_ for _ in ()).throw(_http_error(403)),
    )

    with pytest.raises(HTTPError):
        downloader.fetch_subtitle_bytes(VTT_URL, subtitle_format=SubtitleFormat.VTT)


def test_server_errors_are_retried_with_backoff(monkeypatch):
    attempts = []
    sleeps = []

    def fake_urlopen(request, timeout=None):
        attempts.append(True)
        if len(attempts) <= 2:
            raise _http_error(500)
        return _FakeResponse(VTT_BODY)

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)
    monkeypatch.setattr(downloader.time, "sleep", sleeps.append)

    payload = downloader.fetch_subtitle_bytes(
        VTT_URL, subtitle_format=SubtitleFormat.VTT
    )

    assert payload == VTT_BODY
    assert len(attempts) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_server_errors_give_up_after_retries(monkeypatch):
    attempts = []

    def fake_urlopen(request, timeout=None):
        attempts.append(True)
        raise _http_error(503)

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)
    monkeypatch.setattr(downloader.time, "sleep", lambda *_: None)

    with pytest.raises(HTTPError):
        downloader.fetch_subtitle_bytes(VTT_URL, subtitle_format=SubtitleFormat.VTT)

    assert len(attempts) == downloader._FETCH_RETRIES + 1


def test_connection_errors_are_retried_then_raised(monkeypatch):
    attempts = []

    def fake_urlopen(request, timeout=None):
        attempts.append(True)
        raise URLError("dns")

    monkeypatch.setattr(downloader, "urlopen", fake_urlopen)
    monkeypatch.setattr(downloader.time, "sleep", lambda *_: None)

    with pytest.raises(URLError):
        downloader.fetch_subtitle_bytes(VTT_URL, subtitle_format=SubtitleFormat.VTT)

    assert len(attempts) == downloader._FETCH_RETRIES + 1


# --- string classification ----------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: HTTP Error 429: Too Many Requests", True),
        ("too many requests", True),
        ("sign in to confirm you're not a bot", False),
        ("Video unavailable", False),
    ],
)
def test_looks_rate_limited(message, expected):
    assert looks_rate_limited(message) is expected


# --- models --------------------------------------------------------------


def test_rate_limited_file_allows_error_and_retry_after():
    file = SubtitleFile(
        requested=LangCodeRequested("en"),
        resolved=LangCodeResolved("en"),
        source=SubtitleSource.MANUAL,
        status=DownloadStatus.RATE_LIMITED,
        error="HTTP 429",
        retry_after=12,
    )
    assert file.retry_after == 12

    with pytest.raises(ValueError):
        SubtitleFile(
            requested=LangCodeRequested("en"),
            resolved=None,
            source=None,
            status=DownloadStatus.MISSING,
            error="nope",
        )

    with pytest.raises(ValueError):
        SubtitleFile(
            requested=LangCodeRequested("en"),
            resolved=None,
            source=None,
            status=DownloadStatus.OK,
            retry_after=5,
        )


def _resolved() -> tuple[ResolvedSubtitle, ...]:
    return (
        ResolvedSubtitle(
            requested=LangCodeRequested("en"),
            resolved=LangCodeResolved("en"),
            source=SubtitleSource.MANUAL,
        ),
    )


def _rate_limited_file(retry_after: int | None = 30) -> SubtitleFile:
    return SubtitleFile(
        requested=LangCodeRequested("en"),
        resolved=LangCodeResolved("en"),
        source=SubtitleSource.MANUAL,
        status=DownloadStatus.RATE_LIMITED,
        error="HTTP 429",
        retry_after=retry_after,
    )


def test_result_properties_aggregate_rate_limits(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kw: MOCK_VIDEO_INFO_OK
    )
    monkeypatch.setattr(
        "yt_subs.client.download_subtitles", lambda *a, **k: (_rate_limited_file(45),)
    )

    result = YtSubs(languages="en", output_dir=tmp_path).download(
        "https://www.youtube.com/watch?v=abc123"
    )

    assert result.is_rate_limited is True
    assert len(result.rate_limited_subs) == 1
    assert result.retry_after == 45
    assert result.ok_subs == ()


# --- client behaviour ----------------------------------------------------


def test_strict_download_raises_rate_limited(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kw: MOCK_VIDEO_INFO_OK
    )
    monkeypatch.setattr(
        "yt_subs.client.download_subtitles", lambda *a, **k: (_rate_limited_file(30),)
    )

    client = YtSubs(languages="en", output_dir=tmp_path)
    with pytest.raises(RateLimitedError) as excinfo:
        client.download("https://www.youtube.com/watch?v=abc123", strict=True)

    assert excinfo.value.retry_after == 30
    assert excinfo.value.video_id == "abc123"


def test_strict_download_raises_for_missing(monkeypatch, tmp_path):
    missing = SubtitleFile(
        requested=LangCodeRequested("en"),
        resolved=LangCodeResolved("en"),
        source=SubtitleSource.MANUAL,
        status=DownloadStatus.MISSING,
    )
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kw: MOCK_VIDEO_INFO_OK
    )
    monkeypatch.setattr("yt_subs.client.download_subtitles", lambda *a, **k: (missing,))

    client = YtSubs(languages="en", output_dir=tmp_path)
    with pytest.raises(SubtitleDownloadError):
        client.download("https://www.youtube.com/watch?v=abc123", strict=True)


def test_non_strict_download_returns_rate_limited_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kw: MOCK_VIDEO_INFO_OK
    )
    monkeypatch.setattr(
        "yt_subs.client.download_subtitles", lambda *a, **k: (_rate_limited_file(),)
    )

    result = YtSubs(languages="en", output_dir=tmp_path).download(
        "https://www.youtube.com/watch?v=abc123"
    )
    assert result.subtitles[0].status == DownloadStatus.RATE_LIMITED


def _patch_rate_limited_downloads(monkeypatch):
    """Every video resolves, and every caption fetch is rate-limited."""
    monkeypatch.setattr(
        "yt_subs.client.extract_info",
        lambda url, **kw: {**MOCK_VIDEO_INFO_OK, "id": url.rsplit("/", 1)[-1]},
    )
    monkeypatch.setattr(
        "yt_subs.client.download_subtitles", lambda *a, **k: (_rate_limited_file(),)
    )


def test_download_many_stops_after_consecutive_rate_limits(monkeypatch):
    _patch_rate_limited_downloads(monkeypatch)

    urls = [f"https://x.test/v{i}" for i in range(10)]
    results = list(
        YtSubs(languages="en").download_many(urls, max_consecutive_rate_limits=3)
    )

    assert len(results) == 3
    assert all(r.is_rate_limited for r in results)


def test_download_many_resets_the_counter_on_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "yt_subs.client.extract_info",
        lambda url, **kw: {**MOCK_VIDEO_INFO_OK, "id": url.rsplit("/", 1)[-1]},
    )

    def fake_download_subtitles(*args, **kwargs):
        if str(kwargs["video_id"]).startswith("rl"):
            return (_rate_limited_file(),)
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=SubtitleSource.MANUAL,
                status=DownloadStatus.OK,
                sub_path=Path("ok.vtt"),
                format=SubtitleFormat.VTT,
            ),
        )

    monkeypatch.setattr("yt_subs.client.download_subtitles", fake_download_subtitles)

    urls = [
        "https://x.test/rl1",
        "https://x.test/ok1",
        "https://x.test/rl2",
        "https://x.test/rl3",
        "https://x.test/rl4",
    ]
    results = list(
        YtSubs(languages="en").download_many(urls, max_consecutive_rate_limits=2)
    )

    # rl1 (1), ok1 (reset), rl2 (1), rl3 (2 -> stop). rl4 is never fetched.
    assert [r.video_id for r in results] == ["rl1", "ok1", "rl2", "rl3"]


def test_download_many_breaker_sees_strict_rate_limit_errors(monkeypatch):
    """strict=True raises, but the breaker must still recognise the 429."""
    _patch_rate_limited_downloads(monkeypatch)

    urls = [f"https://x.test/v{i}" for i in range(6)]
    results = list(
        YtSubs(languages="en").download_many(
            urls, max_consecutive_rate_limits=2, strict=True
        )
    )

    assert len(results) == 2
    assert all(r.is_rate_limited for r in results)
    assert results[0].retry_after == 30
    assert results[0].video_id == "v0"


def test_download_many_without_limit_never_stops(monkeypatch):
    _patch_rate_limited_downloads(monkeypatch)

    urls = [f"https://x.test/v{i}" for i in range(4)]
    results = list(YtSubs(languages="en").download_many(urls))

    assert len(results) == 4


def test_download_many_rejects_bad_limit():
    with pytest.raises(ValueError):
        list(YtSubs(languages="en").download_many([], max_consecutive_rate_limits=0))
