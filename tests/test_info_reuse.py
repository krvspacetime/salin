import pytest

import yt_subs
from tests.fixtures import MOCK_VIDEO_INFO_OK
from yt_subs import YtSubs
from yt_subs.error import YtSubsValueError
from yt_subs.shared.models import (
    DownloadStatus,
    LangCodeRequested,
    LangCodeResolved,
    SubtitleFile,
    SubtitleFormat,
    SubtitleSource,
)

URL = "https://www.youtube.com/watch?v=abc123"


def test_extract_info_is_importable_from_the_package_root():
    assert yt_subs.extract_info is yt_subs.core.extract_info


def _exploding_extract(url, **kwargs):
    raise AssertionError(f"extract_info() must not be called, got {url!r}")


def _patch_extract(monkeypatch):
    calls = []

    def fake_extract(url, **kwargs):
        calls.append(url)
        return dict(MOCK_VIDEO_INFO_OK)

    monkeypatch.setattr("yt_subs.client.extract_info", fake_extract)
    return calls


def _patch_downloader(monkeypatch, tmp_path):
    calls = []

    def fake_download_subtitles(*args, **kwargs):
        calls.append(kwargs)
        path = tmp_path / f"{kwargs['video_id']}.en.{kwargs['subtitle_format']}"
        path.write_text("WEBVTT", encoding="utf-8")
        return (
            SubtitleFile(
                requested=LangCodeRequested("en"),
                resolved=LangCodeResolved("en"),
                source=SubtitleSource.MANUAL,
                status=DownloadStatus.OK,
                sub_path=path,
                format=SubtitleFormat.VTT,
            ),
        )

    monkeypatch.setattr("yt_subs.client.download_subtitles", fake_download_subtitles)
    return calls


def test_inspect_reuses_passed_info(monkeypatch):
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    client = YtSubs()
    availability = client.inspect(URL, info=MOCK_VIDEO_INFO_OK)

    assert availability.video_id == "abc123"
    assert "en" in availability.manual
    assert "de" in availability.auto


def test_resolve_reuses_passed_info(monkeypatch):
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    client = YtSubs(languages="en")
    resolved = client.resolve(URL, info=MOCK_VIDEO_INFO_OK)

    assert resolved[0].requested == "en"
    assert resolved[0].resolved == "en"
    assert resolved[0].source == "manual"


def test_download_reuses_passed_info(monkeypatch, tmp_path):
    calls = _patch_downloader(monkeypatch, tmp_path)
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    client = YtSubs(languages="en", output_dir=tmp_path)
    result = client.download(URL, info=MOCK_VIDEO_INFO_OK)

    assert result.video_id == "abc123"
    assert len(result.ok_subs) == 1
    assert calls[0]["info"]["id"] == "abc123"


def test_download_passes_the_info_object_through_unchanged(monkeypatch, tmp_path):
    calls = _patch_downloader(monkeypatch, tmp_path)
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    info = MOCK_VIDEO_INFO_OK
    YtSubs(languages="en", output_dir=tmp_path).download(URL, info=info)

    assert calls[0]["info"] is info


@pytest.mark.parametrize(
    "bad_info",
    [
        {"id": "abc123"},
        {"id": "", "extractor": "youtube", "_type": "video"},
        {"id": "abc123", "extractor": "youtube", "_type": "playlist"},
        {"id": "abc123", "extractor": "youtube", "_type": "url_transparent"},
        "not a dict",
        123,
        ["abc123"],
    ],
)
def test_invalid_info_is_rejected_by_every_entry_point(monkeypatch, bad_info):
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)
    client = YtSubs(languages="en")

    with pytest.raises(YtSubsValueError):
        client.inspect(URL, info=bad_info)

    with pytest.raises(YtSubsValueError):
        client.resolve(URL, info=bad_info)

    with pytest.raises(YtSubsValueError):
        client.download(URL, info=bad_info)


def test_invalid_info_is_rejected_before_downloading(monkeypatch):
    monkeypatch.setattr(
        "yt_subs.client.download_subtitles",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download")),
    )
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    with pytest.raises(YtSubsValueError):
        YtSubs(languages="en").download(
            URL, info={"id": "abc123", "subtitles": {"en": [{"ext": "vtt"}]}}
        )


def test_missing_info_still_extracts_once_per_call(monkeypatch):
    calls = _patch_extract(monkeypatch)

    client = YtSubs(languages="en")
    client.inspect(URL)
    client.resolve(URL)

    assert calls == [URL, URL]


def test_pipeline_shares_one_extraction(monkeypatch, tmp_path):
    calls = _patch_downloader(monkeypatch, tmp_path)
    monkeypatch.setattr("yt_subs.client.extract_info", _exploding_extract)

    client = YtSubs(languages="en", output_dir=tmp_path)
    info = MOCK_VIDEO_INFO_OK

    availability = client.inspect(URL, info=info)
    resolved = client.resolve(URL, info=info)
    result = client.download(URL, info=info)

    assert availability.video_id == "abc123"
    assert resolved[0].resolved == "en"
    assert result.ok_subs[0].sub_path == tmp_path / "abc123.en.vtt"
    assert calls[0]["info"] is info
