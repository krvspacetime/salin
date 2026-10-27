import pytest
from pathlib import Path

from yt_subs import YtSubs
from yt_subs.shared.models import (
    DownloadStatus,
    SubtitleFormat,
    SubtitleFile,
    LangCodeRequested,
    LangCodeResolved,
    SubtitleSource,
)
from yt_subs.error import VideoUnavailableError, YtSubsValueError
from tests.fixtures import (
    MOCK_VIDEO_INFO_OK,
    MOCK_VTT_CONTENT,
)


def test_client_inspect(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    client = YtSubs(languages="en")
    availability = client.inspect("https://www.youtube.com/watch?v=abc123")

    assert availability.video_id == "abc123"
    assert "en" in availability.manual
    assert "de" in availability.auto


def test_invalid_format_override_raises_yt_subs_error():
    client = YtSubs(languages="en")

    with pytest.raises(YtSubsValueError):
        client.download(
            "https://www.youtube.com/watch?v=abc123", subtitle_format="vvtt"
        )

    with pytest.raises(YtSubsValueError):
        YtSubs(languages="en", language_match="exactly")


def test_download_many_survives_bad_format_override():
    client = YtSubs(languages="en")
    urls = [
        "https://www.youtube.com/watch?v=one",
        "https://www.youtube.com/watch?v=two",
    ]

    results = list(client.download_many(urls, subtitle_format="vvtt"))

    assert len(results) == 2
    for result in results:
        assert result.subtitles[0].status == DownloadStatus.ERROR
        assert result.subtitles[0].error is not None


def test_download_many_survives_bad_languages_override(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    def mock_download_subtitles(*args, **kwargs):
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=SubtitleSource.MANUAL,
                status=DownloadStatus.OK,
                sub_path=Path("dummy_path.vtt"),
                format=SubtitleFormat.VTT,
            ),
        )

    monkeypatch.setattr("yt_subs.client.download_subtitles", mock_download_subtitles)

    client = YtSubs()
    results = list(
        client.download_many(
            ["https://www.youtube.com/watch?v=one"], languages={"en": ["es-ES"]}
        )
    )

    assert len(results) == 1
    assert results[0].subtitles == ()
    assert results[0].video_id == "unknown"


def test_download_many_survives_filesystem_errors(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    def mock_download_subtitles(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("yt_subs.client.download_subtitles", mock_download_subtitles)

    client = YtSubs(languages="en")
    results = list(client.download_many(["https://www.youtube.com/watch?v=one"]))

    assert len(results) == 1
    assert results[0].subtitles[0].status == DownloadStatus.ERROR
    error = results[0].subtitles[0].error
    assert error is not None
    assert "disk full" in error


def test_client_resolve(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    client = YtSubs(languages="en")
    resolved = client.resolve("https://www.youtube.com/watch?v=abc123")

    assert len(resolved) == 1
    assert resolved[0].requested == "en"
    assert resolved[0].resolved == "en"
    assert resolved[0].source == "manual"


def test_client_download_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    def mock_download_subtitles(*args, **kwargs):
        output_dir = kwargs["output_dir"]
        video_id = kwargs["video_id"]
        subtitle_format = kwargs["subtitle_format"]
        path = output_dir / f"{video_id}.en.{subtitle_format}"
        path.write_text(MOCK_VTT_CONTENT, encoding="utf-8")
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=SubtitleSource.MANUAL,
                status=DownloadStatus.OK,
                sub_path=path,
                format=subtitle_format,
            ),
        )

    monkeypatch.setattr("yt_subs.client.download_subtitles", mock_download_subtitles)

    client = YtSubs(languages="en", output_dir=tmp_path)
    result = client.download("https://www.youtube.com/watch?v=abc123")

    assert result.video_id == "abc123"
    assert len(result.ok_subs) == 1
    assert result.ok_subs[0].status == DownloadStatus.OK
    sub_path = result.ok_subs[0].sub_path
    assert sub_path is not None
    assert sub_path.exists()


def test_client_download_many_graceful_failures(monkeypatch):
    call_count = 0

    def mock_extract_info(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "fail" in url:
            raise VideoUnavailableError("Video is unavailable")
        return MOCK_VIDEO_INFO_OK

    monkeypatch.setattr("yt_subs.client.extract_info", mock_extract_info)

    def mock_download_subtitles(*args, **kwargs):
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=SubtitleSource.MANUAL,
                status=DownloadStatus.OK,
                sub_path=Path("dummy_path.vtt"),
                format=SubtitleFormat.VTT,
            ),
        )

    monkeypatch.setattr("yt_subs.client.download_subtitles", mock_download_subtitles)

    client = YtSubs(languages="en")
    urls = [
        "https://www.youtube.com/watch?v=fail",
        "https://www.youtube.com/watch?v=success",
    ]

    results = list(client.download_many(urls, max_workers=1))
    assert len(results) == 2

    failed_result = results[0]
    assert failed_result.video_id == "unknown"
    assert failed_result.subtitles[0].status == DownloadStatus.ERROR
    assert failed_result.subtitles[0].error is not None
    assert "Video is unavailable" in failed_result.subtitles[0].error

    success_result = results[1]
    assert success_result.video_id == "abc123"
    assert success_result.subtitles[0].status == DownloadStatus.OK

    results_multi = list(client.download_many(urls, max_workers=2))
    assert len(results_multi) == 2
    failed_res_multi = next(r for r in results_multi if r.url == urls[0])
    assert failed_res_multi.video_id == "unknown"
    assert failed_res_multi.subtitles[0].status == DownloadStatus.ERROR


def test_client_constructor_no_languages_inspect_works(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.extract_info", lambda url, **kwargs: MOCK_VIDEO_INFO_OK
    )

    client = YtSubs()
    availability = client.inspect("https://www.youtube.com/watch?v=abc123")

    assert availability.video_id == "abc123"
    assert "en" in availability.manual
    assert "de" in availability.auto
