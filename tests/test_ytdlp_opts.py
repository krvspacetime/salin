from pathlib import Path

import pytest

from salin import Salin
from salin.core.ytdlp_opts import normalize_cookies, subtitle_download_opts
from salin.error import SalinValueError
from salin.shared.models import (
    DownloadStatus,
    LangCodeRequested,
    LangCodeResolved,
    SubtitleFile,
    SubtitleFormat,
    VideoId,
    YtdlpVideoInfo,
)


def _base_opts() -> dict:
    return subtitle_download_opts(
        output_dir=Path("."),
        video_id=VideoId("abc123"),
        subtitle_format=SubtitleFormat.VTT,
        resolved_langs=["en"],
        skip_video=True,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
    )


def test_extract_opts_are_silent():
    from salin.core.ytdlp_opts import base_extract_opts

    opts = base_extract_opts()

    assert opts["quiet"] is True
    assert opts["no_warnings"] is True
    assert opts["skip_download"] is True


def test_cookies_are_off_by_default():
    assert "cookiesfrombrowser" not in _base_opts()


def test_download_opts_are_silent():
    opts = _base_opts()

    assert opts["quiet"] is True
    assert opts["no_warnings"] is True
    assert opts["noprogress"] is True


def test_cookies_are_forwarded_when_requested():
    opts = subtitle_download_opts(
        output_dir=Path("."),
        video_id=VideoId("abc123"),
        subtitle_format=SubtitleFormat.VTT,
        resolved_langs=["en"],
        skip_video=True,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        cookies=("firefox", "myprofile", None, None),
    )
    assert opts["cookiesfrombrowser"] == ("firefox", "myprofile", None, None)


def test_normalize_cookies_browser_only():
    assert normalize_cookies("chrome") == ("chrome", None, None, None)
    assert normalize_cookies("Firefox") == ("firefox", None, None, None)
    assert normalize_cookies(None) is None
    assert normalize_cookies("") is None


def test_normalize_cookies_profile_keyring_container():
    assert normalize_cookies("firefox:myprofile") == (
        "firefox",
        "myprofile",
        None,
        None,
    )
    assert normalize_cookies("firefox+gnomekeyring") == (
        "firefox",
        None,
        "GNOMEKEYRING",
        None,
    )
    assert normalize_cookies("chromium::Container 1") == (
        "chromium",
        None,
        None,
        "Container 1",
    )


def test_normalize_cookies_rejects_unknown_browser():
    with pytest.raises(SalinValueError):
        normalize_cookies("netscape")


def test_normalize_cookies_rejects_malformed_spec():
    with pytest.raises(SalinValueError):
        normalize_cookies("chrome:")


def test_client_cookies_are_opt_in():
    assert Salin().cookies is None
    assert Salin(cookies="firefox:work").cookies == ("firefox", "work", None, None)

    with pytest.raises(SalinValueError):
        Salin(cookies="not-a-browser")


def _mock_info() -> YtdlpVideoInfo:
    return {
        "id": "abc123",
        "title": "t",
        "subtitles": {"en": [{"ext": "vtt"}]},
        "automatic_captions": {},
    }


def test_client_download_validates_cookies_override(monkeypatch):
    captured: dict = {}

    def fake_download_subtitles(*args, **kwargs):
        captured.update(kwargs)
        return ()

    monkeypatch.setattr("salin.client.download_subtitles", fake_download_subtitles)
    monkeypatch.setattr("salin.client.extract_info", lambda url, **kwargs: _mock_info())

    client = Salin(languages="en")
    client.download("https://x.test/v", cookies="chrome")
    assert captured["cookies"] == ("chrome", None, None, None)

    with pytest.raises(SalinValueError):
        client.download("https://x.test/v", cookies="not-a-browser")


def test_cookies_override_reaches_download_many(monkeypatch):
    monkeypatch.setattr("salin.client.extract_info", lambda url, **kwargs: _mock_info())

    def fake_download_subtitles(*args, **kwargs):
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=None,
                status=DownloadStatus.OK,
                sub_path=Path("dummy.vtt"),
                format=SubtitleFormat.VTT,
            ),
        )

    monkeypatch.setattr("salin.client.download_subtitles", fake_download_subtitles)

    client = Salin(languages="en")
    results = list(client.download_many(["https://x.test/v"], cookies="firefox"))
    assert results[0].subtitles[0].status == DownloadStatus.OK
