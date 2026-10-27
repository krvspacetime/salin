"""Tests for the per-thread YoutubeDL instance pool in the extractor."""

from __future__ import annotations

import threading

import pytest

from salin.core import extractor
from salin.error import VideoUnavailableError
from salin.shared.models import UrlStr

URL = "https://www.youtube.com/watch?v=abc123"
OTHER_URL = "https://www.youtube.com/watch?v=zzz999zzz9"


class _CountingYDL:
    """Stand-in for yt_dlp.YoutubeDL that records how often it is built."""

    built: list[dict] = []

    def __init__(self, opts):
        type(self).built.append(opts)

    def extract_info(self, url, download=False):
        return {"id": "abc123", "title": "t"}

    def close(self):
        pass


@pytest.fixture
def counting_ytdl(monkeypatch):
    _CountingYDL.built = []
    extractor.close_ydl_pool()
    monkeypatch.setattr(extractor.yt_dlp, "YoutubeDL", _CountingYDL)
    yield _CountingYDL
    extractor.close_ydl_pool()


def test_reuses_one_instance_for_repeated_extracts(counting_ytdl):
    extractor.extract_info(UrlStr(URL))
    extractor.extract_info(UrlStr(OTHER_URL))

    assert len(counting_ytdl.built) == 1


def test_keeps_a_separate_instance_per_option_set(counting_ytdl):
    extractor.extract_info(UrlStr(URL))
    extractor.extract_info(UrlStr(URL), proxy="http://127.0.0.1:8080")
    extractor.extract_info(UrlStr(URL), cookiefile="/tmp/cookies.txt")

    assert len(counting_ytdl.built) == 3


def test_pool_is_isolated_per_thread(counting_ytdl):
    extractor.extract_info(UrlStr(URL))

    def worker() -> None:
        extractor.extract_info(UrlStr(URL))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    # One build in the main thread and one in the worker thread.
    assert len(counting_ytdl.built) == 2

    # The main thread keeps reusing its own instance afterwards.
    extractor.extract_info(UrlStr(URL))
    assert len(counting_ytdl.built) == 2


def test_close_ydl_pool_forces_a_rebuild(counting_ytdl):
    extractor.extract_info(UrlStr(URL))
    extractor.close_ydl_pool()
    extractor.extract_info(UrlStr(URL))

    assert len(counting_ytdl.built) == 2


def test_close_ydl_pool_closes_cached_instances(monkeypatch):
    closed: list[_CountingYDL] = []

    class _Closable(_CountingYDL):
        def close(self):
            closed.append(self)

    monkeypatch.setattr(extractor.yt_dlp, "YoutubeDL", _Closable)
    extractor.close_ydl_pool()
    extractor.extract_info(UrlStr(URL))

    extractor.close_ydl_pool()

    assert len(closed) == 1


def test_pool_survives_extraction_errors(counting_ytdl, monkeypatch):
    calls = {"n": 0}

    def boom(self, url, download=False):
        calls["n"] += 1
        raise extractor.yt_dlp.utils.DownloadError("Video unavailable")

    monkeypatch.setattr(_CountingYDL, "extract_info", boom)

    for _ in range(2):
        with pytest.raises(VideoUnavailableError):
            extractor.extract_info(UrlStr(URL))

    # The failed call is retried on the pooled instance, not rebuilt.
    assert calls["n"] == 2
    assert len(counting_ytdl.built) == 1
