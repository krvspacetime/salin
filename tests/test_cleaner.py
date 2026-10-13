import json

import pytest

from yt_subs.cleaner import clean_cues, clean_transcript
from yt_subs.cleaner.dedup import deduplicate_blocks, sanitize_word
from yt_subs.cleaner.normalize import normalize_caption_text
from yt_subs.cleaner.parsers import (
    SUPPORTED_FORMATS,
    parse_srt_cues,
    parse_vtt_cues,
    read_cues,
)
from yt_subs.error import UnsupportedFormatError, YtSubsError
from yt_subs.shared.models import (
    DownloadStatus,
    LangCodeRequested,
    LangCodeResolved,
    SubtitleFile,
    SubtitleFormat,
    SubtitleResult,
    SubtitleSource,
    UrlStr,
    VideoId,
)

VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
never gonna

00:00:03.000 --> 00:00:05.000
never gonna give you up

00:00:05.000 --> 00:00:07.000
give you up
"""

SRT = """1
00:00:01,000 --> 00:00:03,000
never gonna

2
00:00:03,000 --> 00:00:05,000
never gonna give you up

3
00:00:05,000 --> 00:00:07,000
give you up
"""


def _subtitle(path, fmt):
    return SubtitleFile(
        requested=LangCodeRequested("en"),
        resolved=LangCodeResolved("en"),
        source=SubtitleSource.MANUAL,
        status=DownloadStatus.OK,
        sub_path=path,
        format=fmt,
    )


def _result(*subs):
    return SubtitleResult(
        url=UrlStr("https://www.youtube.com/watch?v=abc123"),
        video_id=VideoId("abc123"),
        title="t",
        subtitles=tuple(subs),
    )


def test_supported_formats_starts_with_srt_and_vtt():
    assert SUPPORTED_FORMATS == (SubtitleFormat.SRT, SubtitleFormat.VTT)


def test_normalize_strips_markup_and_stage_directions():
    assert normalize_caption_text("<c>hello</c> &amp; hi") == "hello & hi"
    assert normalize_caption_text("[Music] hello") == "hello"
    assert normalize_caption_text("hello (laughter)") == "hello"
    assert normalize_caption_text("♪ hello") == "hello"
    assert normalize_caption_text(">> Speaker: hello") == "Speaker: hello"


def test_sanitize_word_strips_punctuation_and_case():
    assert sanitize_word("Hello,") == "hello"
    assert sanitize_word("...") == ""


def test_punctuation_only_tokens_never_match():
    # "..." and "--" both sanitize to ""; if they compared equal the
    # unrelated blocks below would be merged into one.
    merged = deduplicate_blocks(["... one two", "-- one two"])
    assert merged == "... one two -- one two"


def test_dedup_collapses_rolling_overlap():
    blocks = ["never gonna", "never gonna give you up", "give you up"]
    assert deduplicate_blocks(blocks) == "never gonna give you up"


def test_dedup_keeps_unrelated_blocks():
    assert deduplicate_blocks(["alpha beta", "gamma delta"]) == (
        "alpha beta gamma delta"
    )


def test_dedup_ignores_empty_blocks():
    assert deduplicate_blocks(["", "  ", "hello"]) == "hello"


def test_srt_keeps_digit_only_caption_text():
    cues = parse_srt_cues(
        [
            "1",
            "00:00:01,000 --> 00:00:02,000",
            "2024",
            "",
        ]
    )
    assert len(cues) == 1
    assert cues[0].text == "2024"
    assert cues[0].index == 0


def test_srt_and_vtt_parse_identically():
    assert [
        (c.index, c.start_ms, c.end_ms, c.text)
        for c in parse_srt_cues(SRT.splitlines())
    ] == [
        (c.index, c.start_ms, c.end_ms, c.text)
        for c in parse_vtt_cues(VTT.splitlines())
    ]


def test_cue_timestamps_are_milliseconds():
    cues = parse_vtt_cues(VTT.splitlines())
    assert cues[0].start_ms == 1_000
    assert cues[0].end_ms == 3_000
    assert cues[2].end_ms == 7_000


def test_vtt_accepts_short_timestamps_and_bom(tmp_path):
    path = tmp_path / "a.en.vtt"
    path.write_text(
        "\ufeffWEBVTT\n\n01:02.000 --> 01:04.000\nhello\n", encoding="utf-8"
    )
    cues = read_cues(path, SubtitleFormat.VTT)
    assert cues[0].start_ms == 62_000
    assert cues[0].end_ms == 64_000


def test_vtt_skips_header_lines(tmp_path):
    path = tmp_path / "a.en.vtt"
    path.write_text(VTT, encoding="utf-8")
    assert len(read_cues(path, SubtitleFormat.VTT)) == 3


def test_unsupported_format_raises_library_error(tmp_path):
    path = tmp_path / "a.en.json3"
    path.write_text(json.dumps({"events": []}), encoding="utf-8")

    with pytest.raises(UnsupportedFormatError) as exc:
        read_cues(path, SubtitleFormat.JSON3)

    assert isinstance(exc.value, YtSubsError)
    assert isinstance(exc.value, NotImplementedError)
    assert "srt" in str(exc.value) and "vtt" in str(exc.value)


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        clean_cues(tmp_path / "nope.en.vtt", SubtitleFormat.VTT)


def test_clean_cues_dedups_rolling_vtt(tmp_path):
    path = tmp_path / "abc.en.vtt"
    path.write_text(VTT, encoding="utf-8")
    assert clean_cues(path, SubtitleFormat.VTT) == "never gonna give you up"


def test_clean_cues_dedups_rolling_srt(tmp_path):
    path = tmp_path / "abc.en.srt"
    path.write_text(SRT, encoding="utf-8")
    assert clean_cues(path, SubtitleFormat.SRT) == "never gonna give you up"


def test_clean_transcript_writes_next_to_source_by_default(tmp_path):
    path = tmp_path / "abc.en.vtt"
    path.write_text(VTT, encoding="utf-8")

    written = clean_transcript(_result(_subtitle(path, SubtitleFormat.VTT)))

    assert written == (tmp_path / "abc.en.txt",)
    assert written[0].read_text(encoding="utf-8") == "never gonna give you up"


def test_clean_transcript_honours_output_dir(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    path = src_dir / "abc.en.vtt"
    path.write_text(VTT, encoding="utf-8")
    out = tmp_path / "out"

    written = clean_transcript(
        _result(_subtitle(path, SubtitleFormat.VTT)), output_dir=out
    )

    assert written == (out / "abc.en.txt",)
    assert not (src_dir / "abc.en.txt").exists()


def test_clean_transcript_accepts_plain_iterable(tmp_path):
    path = tmp_path / "abc.en.vtt"
    path.write_text(VTT, encoding="utf-8")

    written = clean_transcript([_subtitle(path, SubtitleFormat.VTT)])

    assert len(written) == 1


def test_clean_transcript_skips_non_ok_subtitles(tmp_path):
    path = tmp_path / "abc.en.vtt"
    path.write_text(VTT, encoding="utf-8")
    missing = SubtitleFile(
        requested=LangCodeRequested("de"),
        resolved=None,
        source=None,
        status=DownloadStatus.MISSING,
    )

    result = _result(_subtitle(path, SubtitleFormat.VTT), missing)
    written = clean_transcript(result, output_dir=tmp_path / "out")

    assert len(written) == 1


def test_clean_transcript_returns_empty_when_nothing_downloaded():
    assert clean_transcript(_result()) == ()


def test_clean_transcript_rejects_zero_workers(tmp_path):
    with pytest.raises(ValueError):
        clean_transcript(_result(), max_workers=0)


def test_clean_transcript_parallel_matches_sequential(tmp_path):
    paths = []
    for i in range(4):
        path = tmp_path / f"v{i}.en.vtt"
        path.write_text(VTT, encoding="utf-8")
        paths.append(_subtitle(path, SubtitleFormat.VTT))

    out = tmp_path / "out"
    serial = clean_transcript(_result(*paths), output_dir=out, max_workers=1)
    parallel = clean_transcript(
        _result(*paths), output_dir=tmp_path / "out2", max_workers=4
    )

    assert [p.name for p in parallel] == [p.name for p in serial]
    assert parallel[0].read_text(encoding="utf-8") == "never gonna give you up"
