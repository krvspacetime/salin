from __future__ import annotations

from salin.shared.models import YtdlpVideoInfo

MOCK_VIDEO_INFO_OK: YtdlpVideoInfo = {
    "_type": "video",
    "id": "abc123",
    "extractor": "youtube",
    "title": "Mock Video Title",
    "subtitles": {
        "en": [
            {"ext": "vtt", "url": "https://example.com/en.vtt"},
            {"ext": "srt", "url": "https://example.com/en.srt"},
        ],
        "es": [
            {"ext": "vtt", "url": "https://example.com/es.vtt"},
        ],
    },
    "automatic_captions": {
        "en-orig": [
            {"ext": "vtt", "url": "https://example.com/en-orig.vtt"},
        ],
        "de": [
            {"ext": "vtt", "url": "https://example.com/de_auto.vtt"},
        ],
    },
}

MOCK_VIDEO_INFO_NO_SUBS: YtdlpVideoInfo = {
    "id": "xyz789",
    "title": "Mock Video No Subs",
    "subtitles": {},
    "automatic_captions": {},
}

MOCK_VIDEO_INFO_JSON3: YtdlpVideoInfo = {
    "_type": "video",
    "id": "abc123",
    "extractor": "youtube",
    "title": "Mock Video Title",
    "subtitles": {
        "en": [
            {
                "ext": "json3",
                "url": "https://example.com/en.json3",
                "name": "English",
            },
        ],
    },
    "automatic_captions": {
        "en": [
            {
                "ext": "json3",
                "url": "https://example.com/en-auto.json3",
                "name": "English (auto-generated)",
            },
        ],
    },
}

MOCK_VIDEO_INFO_AUTO_ONLY: YtdlpVideoInfo = {
    "_type": "video",
    "id": "auto123",
    "extractor": "youtube",
    "title": "Mock Video Auto Only",
    "subtitles": {},
    "automatic_captions": {
        "en": [
            {
                "ext": "json3",
                "url": "https://example.com/en-auto.json3",
                "name": "English (auto-generated)",
            },
            {
                "ext": "vtt",
                "url": "https://example.com/en-auto.vtt",
                "name": "English (auto-generated)",
            },
        ],
        "de": [
            {
                "ext": "json3",
                "url": "https://example.com/de-auto.json3?tlang=de",
                "name": "German (auto-translated)",
            },
            {
                "ext": "vtt",
                "url": "https://example.com/de-auto.vtt?tlang=de",
                "name": "German (auto-translated)",
            },
        ],
    },
}

MOCK_JSON3_CONTENT = """{
  "events": [
    {"tStartMs": 1360, "dDurationMs": 1680, "segs": [{"utf8": "Hello world"}]},
    {"tStartMs": 3040, "dDurationMs": 2960,
     "segs": [{"utf8": "This is a test "}, {"utf8": "of the subtitle library."}]},
    {"tStartMs": 6000, "dDurationMs": 1000,
     "segs": [{"utf8": "[Music]"}]},
    {"tStartMs": 7000, "dDurationMs": 500}
  ]
}
"""

MOCK_VTT_CONTENT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
>> SPEAKER: Hello world!

00:00:03.000 --> 00:00:06.000
[Music]
This is a test of the subtitle library.
"""

MOCK_SRT_CONTENT = """1
00:00:01,000 --> 00:00:03,000
>> SPEAKER: Hello world!

2
00:00:03,000 --> 00:00:06,000
[Music]
This is a test of the subtitle library.
"""
