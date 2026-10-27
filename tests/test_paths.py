import pytest

from yt_subs.core import downloader
from yt_subs.core.downloader import (
    download_subtitles,
    expected_subtitle_path,
    find_subtitle_file,
    safe_filename_component,
)
from yt_subs.error import SubtitleDownloadError
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

VIDEO_ID = VideoId("abc123")
LANG = LangCodeResolved("en")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc123", "abc123"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("../../evil", "_.._evil"),
        ("..\\..\\evil", "_.._evil"),
        ("a/b", "a_b"),
        ("..", "unknown"),
        ("...", "unknown"),
        ("", "unknown"),
        ("CON", "unknown"),
        ("lpt1", "unknown"),
        ("hi:there", "hi_there"),
        (123, "123"),
    ],
)
def test_safe_filename_component(raw, expected):
    assert safe_filename_component(raw) == expected


def test_expected_subtitle_path_rejects_traversal(tmp_path):
    with pytest.raises(SubtitleDownloadError):
        expected_subtitle_path(tmp_path, VideoId("../evil"), LANG, SubtitleFormat.VTT)

    with pytest.raises(SubtitleDownloadError):
        expected_subtitle_path(
            tmp_path, VideoId("..\\..\\evil"), LANG, SubtitleFormat.VTT
        )

    dest = expected_subtitle_path(tmp_path, VideoId("ok..id"), LANG, SubtitleFormat.VTT)
    assert dest == tmp_path / "ok..id.en.vtt"
    assert dest.parent == tmp_path

    assert (
        expected_subtitle_path(tmp_path, VideoId(".."), LANG, SubtitleFormat.VTT)
        == tmp_path / "...en.vtt"
    )


def test_expected_subtitle_path_coerces_non_str_ids(tmp_path):
    dest = expected_subtitle_path(tmp_path, VideoId("123"), LANG, SubtitleFormat.VTT)
    assert dest == tmp_path / "123.en.vtt"


def test_find_subtitle_file_refuses_to_escape_output_dir(tmp_path):
    with pytest.raises(SubtitleDownloadError):
        find_subtitle_file(tmp_path, VideoId("../evil"), LANG, SubtitleFormat.VTT)

    dest = expected_subtitle_path(tmp_path, VIDEO_ID, LANG, SubtitleFormat.VTT)
    dest.write_bytes(b"WEBVTT")
    assert find_subtitle_file(tmp_path, VIDEO_ID, LANG, SubtitleFormat.VTT) == dest


_DEFAULT_LANG = LangCodeRequested("en")


def _resolved(
    land: LangCodeRequested = _DEFAULT_LANG,
) -> tuple[ResolvedSubtitle, ...]:
    return (
        ResolvedSubtitle(
            requested=land,
            resolved=LangCodeResolved(land),
            source=SubtitleSource.MANUAL,
        ),
    )


def test_download_sanitizes_unsafe_video_id(monkeypatch, tmp_path):
    import yt_subs.core.downloader as downloader

    monkeypatch.setattr(
        downloader,
        "fetch_subtitle_bytes",
        lambda url, **kw: b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n",
    )

    info: YtdlpVideoInfo = {
        "id": "../../evil",
        "title": "t",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}]},
    }

    files = download_subtitles(
        UrlStr("https://www.youtube.com/watch?v=x"),
        resolved_langs=_resolved(),
        video_id=VideoId("../../evil"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
    )

    assert len(files) == 1
    assert files[0].status == DownloadStatus.OK
    sub_path = files[0].sub_path
    assert sub_path is not None
    assert sub_path.parent == tmp_path
    assert sub_path.exists()
    assert sub_path.read_bytes().startswith(b"WEBVTT")

    escaped = list((tmp_path.parent).glob("evil*"))
    assert escaped == []


def test_download_uses_sanitized_id_for_ytdlp_outtmpl(monkeypatch, tmp_path):
    captured = {}

    def fake_ytdlp(*args, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("yt_subs.core.downloader._download_subtitles_ytdlp", fake_ytdlp)

    download_subtitles(
        UrlStr("https://www.youtube.com/watch?v=x"),
        resolved_langs=_resolved(),
        video_id=VideoId("../../evil"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=False,
        info=None,
    )

    assert captured["video_id"] == VideoId("_.._evil")


def test_shared_resolved_track_is_reported_for_every_request(monkeypatch, tmp_path):
    fetched = []

    def fake_fetch(url, *, subtitle_format, timeout=30, **kwargs):
        fetched.append(url)
        return b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n"

    monkeypatch.setattr(downloader, "fetch_subtitle_bytes", fake_fetch)

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {
            "en-orig": [{"ext": "vtt", "url": "https://example.com/en-orig.vtt"}]
        },
    }

    resolved_langs = (
        ResolvedSubtitle(
            requested=LangCodeRequested("en"),
            resolved=LangCodeResolved("en-orig"),
            source=SubtitleSource.MANUAL,
        ),
        ResolvedSubtitle(
            requested=LangCodeRequested("en-orig"),
            resolved=LangCodeResolved("en-orig"),
            source=SubtitleSource.MANUAL,
        ),
    )

    files = download_subtitles(
        UrlStr("https://www.youtube.com/watch?v=x"),
        resolved_langs=resolved_langs,
        video_id=VideoId("abc123"),
        output_dir=tmp_path,
        subtitle_format=SubtitleFormat.VTT,
        sleep_interval_subtitles=0,
        sleep_interval_requests=0,
        skip_video=True,
        info=info,
    )

    assert [f.requested for f in files] == ["en", "en-orig"]
    assert all(f.status == DownloadStatus.OK for f in files)
    assert len({f.sub_path for f in files}) == 1
    assert fetched == ["https://example.com/en-orig.vtt"]


def test_download_rejects_unresolved_items(tmp_path):
    unresolved = ResolvedSubtitle(
        requested=LangCodeRequested("de"),
        resolved=None,
        source=None,
    )

    with pytest.raises(SubtitleDownloadError):
        download_subtitles(
            UrlStr("https://www.youtube.com/watch?v=x"),
            resolved_langs=(unresolved,),
            video_id=VideoId("abc123"),
            output_dir=tmp_path,
            subtitle_format=SubtitleFormat.VTT,
            sleep_interval_subtitles=0,
            sleep_interval_requests=0,
            skip_video=True,
            info={"id": "abc123"},
        )


def test_public_module_still_exports_download_subtitles():
    assert downloader.download_subtitles is download_subtitles


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers = {"Content-Type": "text/vtt; charset=utf-8"}

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._payload
        return self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patch_fetch(monkeypatch, payload: bytes):
    monkeypatch.setattr(
        downloader,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(payload),
    )


def _fetch(url: str, subtitle_format: SubtitleFormat) -> bytes:
    return downloader.fetch_subtitle_bytes(url, subtitle_format=subtitle_format)


def test_fetch_rejects_non_http_urls():
    with pytest.raises(SubtitleDownloadError):
        _fetch("file:///etc/passwd", SubtitleFormat.VTT)

    with pytest.raises(SubtitleDownloadError):
        _fetch("ftp://example.com/en.vtt", SubtitleFormat.VTT)


def test_fetch_rejects_oversized_response(monkeypatch):
    _patch_fetch(monkeypatch, b"WEBVTT" + b"x" * downloader._MAX_SUBTITLE_BYTES)

    with pytest.raises(SubtitleDownloadError):
        _fetch("https://example.com/en.vtt", SubtitleFormat.VTT)


def test_fetch_rejects_html_error_page(monkeypatch):
    _patch_fetch(monkeypatch, b"<!DOCTYPE html><html><body>denied</body></html>")

    with pytest.raises(SubtitleDownloadError):
        _fetch("https://example.com/en.vtt", SubtitleFormat.VTT)


ACCEPTED = [
    (b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n", SubtitleFormat.VTT),
    (b"\xef\xbb\xbfWEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n", SubtitleFormat.VTT),
    (b"1\n00:00:01,000 --> 00:00:03,000\nhi\n", SubtitleFormat.SRT),
    (b'{"events": []}', SubtitleFormat.JSON3),
    (b"<?xml version='1.0'?><timedtext/>", SubtitleFormat.SRV3),
    (b"<?xml version='1.0'?><tt/>", SubtitleFormat.TTML),
    (b"<tt/>", SubtitleFormat.TTML),
]

REJECTED = [
    (b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhi\n", SubtitleFormat.SRT),
    (b"1\n00:00:01,000 --> 00:00:03,000\nhi\n", SubtitleFormat.VTT),
    (b"<!DOCTYPE html><html><body>denied</body></html>", SubtitleFormat.VTT),
    (b"garbage", SubtitleFormat.VTT),
]


def test_fetch_allows_empty_payload_for_caller_to_handle(monkeypatch):
    _patch_fetch(monkeypatch, b"")
    assert _fetch("https://example.com/en.vtt", SubtitleFormat.VTT) == b""


@pytest.mark.parametrize(("payload", "subtitle_format"), ACCEPTED)
def test_fetch_accepts_matching_format(monkeypatch, payload, subtitle_format):
    _patch_fetch(monkeypatch, payload)
    assert _fetch("https://example.com/en", subtitle_format) == payload


@pytest.mark.parametrize(("payload", "subtitle_format"), REJECTED)
def test_fetch_rejects_mismatched_format(monkeypatch, payload, subtitle_format):
    _patch_fetch(monkeypatch, payload)
    with pytest.raises(SubtitleDownloadError):
        _fetch("https://example.com/en", subtitle_format)


def test_direct_download_falls_back_when_response_rejected(monkeypatch, tmp_path):
    fallback_calls = []

    def fake_ytdlp(*args, **kwargs):
        fallback_calls.append(kwargs)
        expected_subtitle_path(
            tmp_path, kwargs["video_id"], LANG, SubtitleFormat.VTT
        ).write_bytes(b"WEBVTT")
        return None

    monkeypatch.setattr("yt_subs.core.downloader._download_subtitles_ytdlp", fake_ytdlp)
    _patch_fetch(monkeypatch, b"<html>denied</html>")

    info: YtdlpVideoInfo = {
        "id": "abc123",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}]},
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

    assert fallback_calls and fallback_calls[0]["video_id"] == VideoId("abc123")
    assert files[0].status == DownloadStatus.OK
