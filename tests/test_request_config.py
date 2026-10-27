from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from tests.fixtures import MOCK_VIDEO_INFO_OK
from yt_subs import YtSubs
from yt_subs.core import downloader, extractor
from yt_subs.core.downloader import download_subtitles
from yt_subs.core.fetcher import FetchedCues
from yt_subs.core.ytdlp_opts import (
    PROXY_SCHEMES,
    base_extract_opts,
    normalize_cookiefile,
    normalize_proxy,
    proxy_supports_direct_fetch,
    subtitle_download_opts,
)
from yt_subs.error import YtSubsValueError
from yt_subs.shared.models import (
    DownloadStatus,
    LangCodeRequested,
    LangCodeResolved,
    ResolvedSubtitle,
    SubtitleFormat,
    SubtitleSource,
    UrlStr,
    VideoId,
    YtdlpVideoInfo,
)

URL = "https://www.youtube.com/watch?v=abc123"
VTT_URL = "https://example.com/en.vtt"
VTT_BODY = b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n"

BROWSER_COOKIES = ("chrome", None, None, None)


def _download_opts(**overrides) -> dict:
    return subtitle_download_opts(
        output_dir=Path("."),
        video_id=VideoId("abc123"),
        subtitle_format=SubtitleFormat.VTT,
        resolved_langs=["en"],
        skip_video=True,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        **overrides,
    )


# --- option builders -----------------------------------------------------


def test_request_options_are_absent_by_default():
    opts = base_extract_opts()

    assert "cookiesfrombrowser" not in opts
    assert "cookiefile" not in opts
    assert "proxy" not in opts

    assert "cookiesfrombrowser" not in _download_opts()
    assert "cookiefile" not in _download_opts()
    assert "proxy" not in _download_opts()


def test_extract_opts_forward_all_request_options():
    opts = base_extract_opts(
        cookies=BROWSER_COOKIES,
        cookiefile="/tmp/cookies.txt",
        proxy="socks5://127.0.0.1:1080",
    )

    assert opts["cookiesfrombrowser"] == BROWSER_COOKIES
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert opts["proxy"] == "socks5://127.0.0.1:1080"


def test_download_opts_forward_all_request_options():
    opts = _download_opts(
        cookies=BROWSER_COOKIES,
        cookiefile="/tmp/cookies.txt",
        proxy="http://user:pass@127.0.0.1:8080",
    )

    assert opts["cookiesfrombrowser"] == BROWSER_COOKIES
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert opts["proxy"] == "http://user:pass@127.0.0.1:8080"


# --- validation ----------------------------------------------------------


def test_normalize_cookiefile_accepts_an_existing_file(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    assert normalize_cookiefile(path) == str(path)
    assert normalize_cookiefile(str(path)) == str(path)
    assert normalize_cookiefile(None) is None


def test_normalize_cookiefile_rejects_missing_path(tmp_path):
    with pytest.raises(YtSubsValueError, match="cookiefile does not exist"):
        normalize_cookiefile(tmp_path / "nope.txt")


def test_normalize_cookiefile_rejects_a_directory(tmp_path):
    with pytest.raises(YtSubsValueError):
        normalize_cookiefile(tmp_path)


@pytest.mark.parametrize("scheme", sorted(PROXY_SCHEMES))
def test_normalize_proxy_accepts_supported_schemes(scheme):
    proxy = f"{scheme}://127.0.0.1:8080"
    assert normalize_proxy(proxy) == proxy


def test_normalize_proxy_accepts_credentials_and_defaults():
    proxy = "http://user:p%40ss@proxy.example.com:3128"
    assert normalize_proxy(proxy) == proxy
    assert normalize_proxy(None) is None
    assert normalize_proxy("") is None


@pytest.mark.parametrize(
    "proxy",
    [
        "ftp://127.0.0.1:21",
        "127.0.0.1:8080",
        "http://",
        "socks5://",
    ],
)
def test_normalize_proxy_rejects_bad_input(proxy):
    with pytest.raises(YtSubsValueError, match="invalid proxy"):
        normalize_proxy(proxy)


@pytest.mark.parametrize(
    ("proxy", "expected"),
    [
        (None, True),
        ("", True),
        ("http://127.0.0.1:8080", True),
        ("https://127.0.0.1:8080", False),
        ("socks5://127.0.0.1:1080", False),
        ("socks5h://127.0.0.1:1080", False),
    ],
)
def test_proxy_supports_direct_fetch(proxy, expected):
    assert proxy_supports_direct_fetch(proxy) is expected


# --- extract_info --------------------------------------------------------


class _FakeYDL:
    captured: list[dict] = []
    extract_calls: list[tuple[str, bool]] = []

    def __init__(self, opts):
        type(self).captured.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        type(self).extract_calls.append((url, download))
        return {"id": "abc123", "title": "t"}


@pytest.fixture
def fake_ytdl(monkeypatch):
    _FakeYDL.captured = []
    _FakeYDL.extract_calls = []
    monkeypatch.setattr(extractor.yt_dlp, "YoutubeDL", _FakeYDL)
    return _FakeYDL


def test_extract_info_passes_request_options_to_ytdlp(fake_ytdl):
    extractor.extract_info(
        UrlStr(URL),
        cookies=BROWSER_COOKIES,
        cookiefile="/tmp/cookies.txt",
        proxy="socks5h://127.0.0.1:1080",
    )

    opts = fake_ytdl.captured[0]
    assert opts["cookiesfrombrowser"] == BROWSER_COOKIES
    assert opts["cookiefile"] == "/tmp/cookies.txt"
    assert opts["proxy"] == "socks5h://127.0.0.1:1080"
    assert fake_ytdl.extract_calls == [(URL, False)]


def test_extract_info_leaves_request_options_out_when_unset(fake_ytdl):
    extractor.extract_info(UrlStr(URL))

    opts = fake_ytdl.captured[0]
    assert "cookiesfrombrowser" not in opts
    assert "cookiefile" not in opts
    assert "proxy" not in opts


# --- client configuration ------------------------------------------------


def test_client_request_config_is_opt_in():
    client = YtSubs()

    assert client.cookies is None
    assert client.cookiefile is None
    assert client.proxy is None


def test_client_stores_normalized_request_config(tmp_path):
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    client = YtSubs(
        cookies="firefox:work",
        cookiefile=path,
        proxy="socks5://127.0.0.1:1080",
    )

    assert client.cookies == ("firefox", "work", None, None)
    assert client.cookiefile == str(path)
    assert client.proxy == "socks5://127.0.0.1:1080"


def test_client_rejects_bad_request_config(tmp_path):
    with pytest.raises(YtSubsValueError):
        YtSubs(cookies="not-a-browser")
    with pytest.raises(YtSubsValueError):
        YtSubs(cookiefile=tmp_path / "missing.txt")
    with pytest.raises(YtSubsValueError):
        YtSubs(proxy="ftp://127.0.0.1:21")


def test_client_inspect_threads_request_config_to_extract(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_extract(url, **kwargs):
        calls.append(kwargs)
        return MOCK_VIDEO_INFO_OK

    monkeypatch.setattr("yt_subs.client.extract_info", fake_extract)

    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    client = YtSubs(
        languages="en",
        cookies="chrome",
        cookiefile=cookiefile,
        proxy="http://127.0.0.1:8080",
    )
    client.inspect(URL)

    assert calls == [
        {
            "cookies": BROWSER_COOKIES,
            "cookiefile": client.cookiefile,
            "proxy": "http://127.0.0.1:8080",
        }
    ]


def test_per_call_request_config_overrides_the_client(monkeypatch):
    calls: list[dict] = []

    def fake_extract(url, **kwargs):
        calls.append(kwargs)
        return MOCK_VIDEO_INFO_OK

    monkeypatch.setattr("yt_subs.client.extract_info", fake_extract)

    client = YtSubs(languages="en", cookies="chrome", proxy="http://a:1")
    client.inspect(URL, cookies="firefox", proxy="http://b:2")

    assert calls[0]["cookies"] == ("firefox", None, None, None)
    assert calls[0]["proxy"] == "http://b:2"


def test_client_download_threads_request_config_to_downloader(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_download_subtitles(*args, **kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr("yt_subs.client.download_subtitles", fake_download_subtitles)
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    cookiefile = tmp_path / "cookies.txt"
    cookiefile.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

    YtSubs(
        languages="en",
        output_dir=tmp_path,
        cookies="chrome",
        cookiefile=cookiefile,
        proxy="socks5://127.0.0.1:1080",
    ).download(URL)

    assert captured["cookies"] == BROWSER_COOKIES
    assert captured["cookiefile"] == str(cookiefile)
    assert captured["proxy"] == "socks5://127.0.0.1:1080"


def test_download_many_forwards_request_overrides(monkeypatch, tmp_path):
    seen: list[str | None] = []

    def fake_download_subtitles(*args, **kwargs):
        seen.append(kwargs["proxy"])
        return ()

    monkeypatch.setattr("yt_subs.client.download_subtitles", fake_download_subtitles)
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    client = YtSubs(languages="en", output_dir=tmp_path)
    list(
        client.download_many(
            ["https://x.test/a", "https://x.test/b"],
            proxy="http://127.0.0.1:8080",
        )
    )

    assert seen == ["http://127.0.0.1:8080", "http://127.0.0.1:8080"]


def test_fetch_threads_proxy_to_the_cue_fetcher(monkeypatch):
    extract_calls: list[dict] = []
    fetch_calls: list[dict] = []

    def fake_extract(url, **kwargs):
        extract_calls.append(kwargs)
        return MOCK_VIDEO_INFO_OK

    def fake_fetch_cues(info, **kwargs):
        fetch_calls.append(kwargs)
        return FetchedCues(
            cues=(),
            resolved=LangCodeResolved("en"),
            source=SubtitleSource.MANUAL,
            subtitle_format=SubtitleFormat.JSON3,
        )

    monkeypatch.setattr("yt_subs.client.extract_info", fake_extract)
    monkeypatch.setattr("yt_subs.client.fetch_transcript_cues", fake_fetch_cues)

    YtSubs(languages="en", proxy="http://127.0.0.1:8080").fetch(URL)

    assert extract_calls[0]["proxy"] == "http://127.0.0.1:8080"
    assert fetch_calls[0]["proxy"] == "http://127.0.0.1:8080"


# --- direct download plumbing -------------------------------------------


def _resolved() -> tuple[ResolvedSubtitle, ...]:
    return (
        ResolvedSubtitle(
            requested=LangCodeRequested("en"),
            resolved=LangCodeResolved("en"),
            source=SubtitleSource.MANUAL,
        ),
    )


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_direct_download_passes_proxy_to_the_byte_fetcher(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_fetch(url, **kwargs):
        captured.update(kwargs)
        return VTT_BODY

    monkeypatch.setattr(downloader, "fetch_subtitle_bytes", fake_fetch)

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": VTT_URL}]},
    }

    download_subtitles(
        UrlStr(URL),
        resolved_langs=_resolved(),
        video_id=VideoId("abc123"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
        cookies=BROWSER_COOKIES,
        cookiefile="/tmp/cookies.txt",
        proxy="http://127.0.0.1:8080",
    )

    assert captured["proxy"] == "http://127.0.0.1:8080"


def test_expired_url_refresh_reuses_the_request_config(monkeypatch, tmp_path):
    """A 403 re-extracts with the same cookies/cookiefile/proxy."""
    extract_calls: list[dict] = []
    proxies_used: list[str | None] = []

    fresh_info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/fresh.vtt"}]},
    }

    def fake_extract(url, **kwargs):
        extract_calls.append(kwargs)
        return fresh_info

    def fake_urlopen(request, timeout=None):
        if request.full_url == VTT_URL:
            raise HTTPError(VTT_URL, 403, "Forbidden", Message(), None)
        return _FakeResponse(VTT_BODY)

    def fake_open(request, *, proxy, timeout):
        proxies_used.append(proxy)
        return fake_urlopen(request, timeout=timeout)

    monkeypatch.setattr(downloader, "extract_info", fake_extract)
    monkeypatch.setattr(downloader, "_open", fake_open)
    monkeypatch.setattr(downloader.time, "sleep", lambda *_: None)

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": VTT_URL}]},
    }

    files = download_subtitles(
        UrlStr(URL),
        resolved_langs=_resolved(),
        video_id=VideoId("abc123"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
        cookies=BROWSER_COOKIES,
        cookiefile="/tmp/cookies.txt",
        proxy="http://127.0.0.1:8080",
    )

    sub_path = files[0].sub_path
    assert sub_path == tmp_path / "abc123.en.vtt"
    assert sub_path is not None
    assert sub_path.read_bytes() == VTT_BODY
    assert proxies_used == ["http://127.0.0.1:8080"] * 2
    assert extract_calls == [
        {
            "cookies": BROWSER_COOKIES,
            "cookiefile": "/tmp/cookies.txt",
            "proxy": "http://127.0.0.1:8080",
        }
    ]


@pytest.mark.parametrize(
    "proxy",
    [
        "https://127.0.0.1:8080",
        "socks4://127.0.0.1:1080",
        "socks4a://127.0.0.1:1080",
        "socks5://127.0.0.1:1080",
        "socks5h://127.0.0.1:1080",
    ],
)
def test_non_http_proxy_skips_the_direct_fetcher(monkeypatch, tmp_path, proxy):
    """urllib cannot speak SOCKS or TLS-to-proxy; yt-dlp does the fetch."""
    direct_calls: list[dict] = []
    ytdlp_calls: list[dict] = []

    def fake_ytdlp(*args, **kwargs):
        ytdlp_calls.append(kwargs)
        return None

    monkeypatch.setattr(
        downloader, "fetch_subtitle_bytes", lambda *a, **k: direct_calls.append(k)
    )
    monkeypatch.setattr(downloader, "_download_subtitles_ytdlp", fake_ytdlp)

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": VTT_URL}]},
    }

    files = download_subtitles(
        UrlStr(URL),
        resolved_langs=_resolved(),
        video_id=VideoId("abc123"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
        proxy=proxy,
    )

    assert direct_calls == []
    assert len(ytdlp_calls) == 1
    assert ytdlp_calls[0]["proxy"] == proxy
    assert files[0].status == DownloadStatus.MISSING


def test_fetch_rejects_a_non_http_proxy_before_extracting(monkeypatch):
    def boom(url, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("extract_info must not run for an unusable proxy")

    monkeypatch.setattr("yt_subs.client.extract_info", boom)

    with pytest.raises(YtSubsValueError, match="http:// proxies"):
        YtSubs(languages="en", proxy="socks5://127.0.0.1:1080").fetch("abc123")
