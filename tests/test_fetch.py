from __future__ import annotations

import pytest

from tests.fixtures import (
    MOCK_JSON3_CONTENT,
    MOCK_VIDEO_INFO_AUTO_ONLY,
    MOCK_VIDEO_INFO_JSON3,
    MOCK_VIDEO_INFO_NO_SUBS,
    MOCK_VIDEO_INFO_OK,
    MOCK_VTT_CONTENT,
)
from yt_subs import FetchedTranscript, TranscriptSnippet, YtSubs
from yt_subs.error import (
    LanguageParseError,
    SubtitleDownloadError,
    TranscriptUnavailableError,
    YtSubsValueError,
)


@pytest.fixture
def patch_bytes(monkeypatch):
    """Serve canned bytes for whatever URL the fetcher asks for."""

    def install(payload: bytes):
        calls: list[tuple[str, str]] = []

        def fake_fetch_subtitle_bytes(url, *, subtitle_format, **kwargs):
            calls.append((url, str(subtitle_format)))
            return payload

        monkeypatch.setattr(
            "yt_subs.core.fetcher.fetch_subtitle_bytes", fake_fetch_subtitle_bytes
        )
        return calls

    return install


def test_fetch_returns_yta_shaped_transcript(monkeypatch, patch_bytes):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_JSON3
    )
    calls = patch_bytes(MOCK_JSON3_CONTENT.encode())

    transcript = YtSubs(languages="en").fetch("https://www.youtube.com/watch?v=abc123")

    assert isinstance(transcript, FetchedTranscript)
    assert transcript.video_id == "abc123"
    assert transcript.language == "English"
    assert transcript.language_code == "en"
    assert transcript.is_generated is False

    assert len(transcript) == 2
    assert [s.text for s in transcript] == [
        "Hello world",
        "This is a test of the subtitle library.",
    ]

    first = transcript[0]
    assert isinstance(first, TranscriptSnippet)
    assert first.start == pytest.approx(1.36)
    assert first.duration == pytest.approx(1.68)

    # json3 is preferred over every other format.
    assert calls == [("https://example.com/en.json3", "json3")]

    assert transcript.to_raw_data() == [
        {"text": "Hello world", "start": 1.36, "duration": 1.68},
        {
            "text": "This is a test of the subtitle library.",
            "start": 3.04,
            "duration": 2.96,
        },
    ]
    assert transcript.text == "Hello world This is a test of the subtitle library."


def test_fetch_accepts_bare_video_id(monkeypatch, patch_bytes):
    seen: list[str] = []

    def fake_extract(url, **kwargs):
        seen.append(url)
        return MOCK_VIDEO_INFO_JSON3

    monkeypatch.setattr("yt_subs.client.extract_info", fake_extract)
    patch_bytes(MOCK_JSON3_CONTENT.encode())

    YtSubs(languages="en").fetch("dQw4w9WgXcQ")

    assert seen == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


def test_fetch_auto_only_is_marked_generated(monkeypatch, patch_bytes):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_AUTO_ONLY
    )
    calls = patch_bytes(MOCK_JSON3_CONTENT.encode())

    transcript = YtSubs(languages="en").fetch("auto123")

    assert transcript.is_generated is True
    assert transcript.language == "English (auto-generated)"
    assert calls == [("https://example.com/en-auto.json3", "json3")]


def test_fetch_ignores_translated_auto_tracks(monkeypatch, patch_bytes):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_AUTO_ONLY
    )
    patch_bytes(MOCK_JSON3_CONTENT.encode())

    # "de" only exists as a tlang auto-translated track, which is not a native
    # caption track, so it must not resolve.
    with pytest.raises(TranscriptUnavailableError):
        YtSubs(languages="de").fetch("auto123")


def test_fetch_falls_back_to_vtt(monkeypatch, patch_bytes):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )
    calls = patch_bytes(MOCK_VTT_CONTENT.encode())

    transcript = YtSubs(languages="en").fetch("https://www.youtube.com/watch?v=abc123")

    assert calls == [("https://example.com/en.vtt", "vtt")]
    assert len(transcript) == 2
    assert transcript[0].text == "SPEAKER: Hello world!"
    assert transcript[0].start == pytest.approx(1.0)
    assert transcript[0].duration == pytest.approx(2.0)
    assert transcript[1].text == "This is a test of the subtitle library."
    assert transcript[1].start == pytest.approx(3.0)


def test_fetch_raises_when_no_transcript(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_NO_SUBS
    )

    with pytest.raises(TranscriptUnavailableError) as excinfo:
        YtSubs(languages="en").fetch("xyz789")

    assert excinfo.value.video_id == "xyz789"
    assert "'en'" in str(excinfo.value)


def test_fetch_requires_languages():
    with pytest.raises(LanguageParseError):
        YtSubs().fetch("abc123")


def test_fetch_rejects_preserve_formatting(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_JSON3
    )

    with pytest.raises(YtSubsValueError, match="preserve_formatting"):
        YtSubs(languages="en").fetch("abc123", preserve_formatting=True)


def test_fetch_wraps_http_errors(monkeypatch):
    from email.message import Message
    from urllib.error import HTTPError

    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_JSON3
    )

    def boom(url, *, subtitle_format, **kwargs):
        raise HTTPError(url, 429, "Too Many Requests", Message(), None)

    monkeypatch.setattr("yt_subs.core.fetcher.fetch_subtitle_bytes", boom)

    with pytest.raises(SubtitleDownloadError, match="HTTP 429"):
        YtSubs(languages="en").fetch("abc123")


def test_fetch_reuses_supplied_info(monkeypatch, patch_bytes):
    def boom(url):  # pragma: no cover - must never run
        raise AssertionError("extract_info should not be called when info is given")

    monkeypatch.setattr("yt_subs.client.extract_info", boom)
    patch_bytes(MOCK_JSON3_CONTENT.encode())

    transcript = YtSubs(languages="en").fetch("abc123", info=MOCK_VIDEO_INFO_JSON3)

    assert transcript.video_id == "abc123"


def test_fetch_rejects_hand_built_info():
    with pytest.raises(YtSubsValueError):
        YtSubs(languages="en").fetch("abc123", info={"id": "abc123"})


def test_fetch_honors_source_policy(monkeypatch, patch_bytes):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_AUTO_ONLY
    )
    patch_bytes(MOCK_JSON3_CONTENT.encode())

    with pytest.raises(TranscriptUnavailableError):
        YtSubs(languages="en", source_policy="manual_only").fetch("auto123")

    transcript = YtSubs(languages="en", source_policy="auto_only").fetch("auto123")
    assert transcript.is_generated is True
