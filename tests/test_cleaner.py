import json

import pytest

from yt_subs.cleaner import clean_cues, clean_transcript
from yt_subs.cleaner.dedup import deduplicate_blocks, sanitize_word
from yt_subs.cleaner.normalize import normalize_caption_text
from yt_subs.cleaner.parsers import (
    CUE_READERS,
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


def test_every_subtitle_format_has_a_parser():
    assert set(SUPPORTED_FORMATS) == set(SubtitleFormat)
    assert len(CUE_READERS) == len(SubtitleFormat)


def test_normalize_strips_markup_and_stage_directions():
    assert normalize_caption_text("<c>hello</c> &amp; hi") == "hello & hi"
    assert normalize_caption_text("[Music] hello") == "hello"
    assert normalize_caption_text("hello (laughter)") == "hello"
    assert normalize_caption_text("♪ hello") == "hello"
    assert normalize_caption_text(">> Speaker: hello") == "Speaker: hello"


def test_normalize_drops_brackets_left_empty_by_music_symbols():
    # A cue that is only "[♪♪♪]" matches no stage keyword, so the brackets
    # would otherwise survive the symbol strip and reach the transcript.
    assert normalize_caption_text("[♪♪♪]") == ""
    assert normalize_caption_text("[♫] hello [♪]") == "hello"
    assert normalize_caption_text("hello ()") == "hello"
    assert normalize_caption_text("♪ We're no strangers to love ♪") == (
        "We're no strangers to love"
    )


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
    cues = parse_srt_cues("1\n00:00:01,000 --> 00:00:02,000\n2024\n")
    assert len(cues) == 1
    assert cues[0].text == "2024"
    assert cues[0].index == 0


def test_srt_and_vtt_parse_identically():
    assert [(c.index, c.start_ms, c.end_ms, c.text) for c in parse_srt_cues(SRT)] == [
        (c.index, c.start_ms, c.end_ms, c.text) for c in parse_vtt_cues(VTT)
    ]


def test_cue_timestamps_are_milliseconds():
    cues = parse_vtt_cues(VTT)
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


def test_unregistered_format_raises_library_error(monkeypatch, tmp_path):
    # Every SubtitleFormat is registered, so reach the guard by unregistering one.
    monkeypatch.delitem(CUE_READERS, SubtitleFormat.JSON3)
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


# --- The remaining formats -------------------------------------------------
#
# Payloads below mirror real YouTube responses for one three-cue excerpt, each
# carrying the same spoken words. srv1/srv2 escape ampersands twice and srv1
# timestamps are seconds, so a parser that gets either wrong fails the
# cross-format equality check rather than looking plausible.

EXPECTED_TRANSCRIPT = (
    "We are no strangers to love You know the rules and so do I "
    "A full commitment is what I am thinking of"
)

VTT_ALL = """WEBVTT

00:00:18.640 --> 00:00:21.880
We are no strangers to love

00:00:22.640 --> 00:00:26.960
You know the rules
and so do I

00:00:27.040 --> 00:00:31.040
A full commitment is what I am thinking of
"""

SRT_ALL = """1
00:00:18,640 --> 00:00:21,880
We are no strangers to love

2
00:00:22,640 --> 00:00:26,960
You know the rules
and so do I

3
00:00:27,040 --> 00:00:31,040
A full commitment is what I am thinking of
"""

JSON3_ALL = json.dumps(
    {
        "wireMagic": "pb3",
        "events": [
            {"tStartMs": 0, "dDurationMs": 0},
            {
                "tStartMs": 18640,
                "dDurationMs": 3240,
                "segs": [{"utf8": "We are no strangers to love"}],
            },
            {
                "tStartMs": 22640,
                "dDurationMs": 4320,
                "segs": [{"utf8": "You know the rules\nand so do I"}],
            },
            {
                "tStartMs": 27040,
                "dDurationMs": 4000,
                "segs": [
                    {"utf8": "A full commitment is "},
                    {"utf8": "what I am thinking of"},
                ],
            },
        ],
    }
)

SRV1_ALL = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="18.64" dur="3.24">We are no strangers to love</text>'
    '<text start="22.64" dur="4.32">You know the rules\nand so do I</text>'
    '<text start="27.04" dur="4">A full commitment is what I am thinking of</text>'
    "</transcript>"
)

SRV2_ALL = (
    '<?xml version="1.0" encoding="utf-8" ?><timedtext>'
    '<text t="18640" d="3240" w="1" r="15" c="1">We are no strangers to love</text>'
    '<text t="18680" d="3200" w="1" append="1"> You know the rules</text>'
    '<text t="18690" d="3190" w="1" append="1">\n</text>'
    '<text t="22640" d="4320" w="1" r="15" c="1">You know the rules</text>'
    '<text t="22680" d="4280" w="1" append="1"> and so do I</text>'
    '<text t="27040" d="4000" w="1" r="15" c="1">A full commitment is </text>'
    '<text t="27080" d="3960" w="1" append="1">what I am thinking of</text>'
    "</timedtext>"
)

SRV3_ALL = (
    '<?xml version="1.0" encoding="utf-8" ?><timedtext format="3">\n<body>\n'
    '<p t="18640" d="3240">We are no strangers to love</p>\n'
    '<p t="22640" d="4320">You know the rules\nand so do I</p>\n'
    '<p t="27040" d="4000">A full commitment is what I am thinking of</p>\n'
    "</body>\n</timedtext>"
)

TTML_ALL = (
    '<?xml version="1.0" encoding="utf-8" ?>\n'
    '<tt xml:lang="en" xmlns="http://www.w3.org/ns/ttml">\n'
    '<body region="r1"><div>\n'
    '<p begin="00:00:18.640" end="00:00:21.880" style="s2">We are no strangers to love</p>\n'
    '<p begin="00:00:22.640" end="00:00:26.960" style="s2">'
    "You know the rules<br />and so do I</p>\n"
    '<p begin="00:00:27.040" end="00:00:31.040" style="s2">'
    "A full commitment is what I am thinking of</p>\n"
    "</div></body></tt>"
)

ALL_FORMATS = [
    (SubtitleFormat.VTT, VTT_ALL),
    (SubtitleFormat.SRT, SRT_ALL),
    (SubtitleFormat.JSON3, JSON3_ALL),
    (SubtitleFormat.SRV1, SRV1_ALL),
    (SubtitleFormat.SRV2, SRV2_ALL),
    (SubtitleFormat.SRV3, SRV3_ALL),
    (SubtitleFormat.TTML, TTML_ALL),
]


@pytest.mark.parametrize(("fmt", "payload"), ALL_FORMATS)
def test_every_format_cleans_to_the_same_transcript(tmp_path, fmt, payload):
    path = tmp_path / f"abc.en.{fmt}"
    path.write_text(payload, encoding="utf-8")
    assert clean_cues(path, fmt) == EXPECTED_TRANSCRIPT


@pytest.mark.parametrize(("fmt", "payload"), ALL_FORMATS)
def test_every_format_yields_three_indexed_cues(tmp_path, fmt, payload):
    path = tmp_path / f"abc.en.{fmt}"
    path.write_text(payload, encoding="utf-8")

    cues = read_cues(path, fmt)

    assert [c.index for c in cues] == [0, 1, 2]
    assert cues[0].start_ms == 18_640
    assert cues[0].end_ms == 21_880
    assert cues[2].start_ms == 27_040


def test_srv1_timestamps_are_seconds_not_milliseconds(tmp_path):
    path = tmp_path / "abc.en.srv1"
    path.write_text(SRV1_ALL, encoding="utf-8")
    assert read_cues(path, SubtitleFormat.SRV1)[0].start_ms == 18_640


def test_srv_double_escaped_entities_are_unescaped(tmp_path):
    # srv1/srv2 ship "&amp;#39;" where srv3 ships "&#39;". A single XML parse
    # leaves the literal text "&#39;" behind, so a second pass is required.
    path = tmp_path / "abc.en.srv2"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8" ?><timedtext>'
        '<text t="0" d="1000">we&amp;#39;re</text>'
        "</timedtext>",
        encoding="utf-8",
    )
    assert read_cues(path, SubtitleFormat.SRV2)[0].text == "we're"


def test_ttml_breaks_become_spaces():
    assert normalize_caption_text("rules<br />and so do I") == "rules and so do I"
    assert normalize_caption_text("rules<br>and") == "rules and"


def test_ttml_accepts_dur_instead_of_end(tmp_path):
    path = tmp_path / "abc.en.ttml"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8" ?><tt><body><div>'
        '<p begin="1s" dur="3.5s">hello</p>'
        "</div></body></tt>",
        encoding="utf-8",
    )
    cues = read_cues(path, SubtitleFormat.TTML)
    assert cues[0].start_ms == 1_000
    assert cues[0].end_ms == 4_500


def test_json3_skips_gap_events_without_segments(tmp_path):
    path = tmp_path / "abc.en.json3"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {"tStartMs": 0, "dDurationMs": 500},
                    {"tStartMs": 1000, "dDurationMs": 500, "segs": []},
                    {"tStartMs": 2000, "dDurationMs": 500, "segs": [{"utf8": "hi"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    cues = read_cues(path, SubtitleFormat.JSON3)

    assert len(cues) == 1
    assert cues[0].index == 0
    assert cues[0].text == "hi"


def test_json3_rejects_malformed_payloads(tmp_path):
    path = tmp_path / "abc.en.json3"

    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError):
        read_cues(path, SubtitleFormat.JSON3)

    path.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_cues(path, SubtitleFormat.JSON3)


@pytest.mark.parametrize("fmt", [f for f, _ in ALL_FORMATS])
def test_missing_file_raises_for_every_format(tmp_path, fmt):
    with pytest.raises(FileNotFoundError):
        read_cues(tmp_path / f"nope.en.{fmt}", fmt)


def test_srv2_groups_append_elements_into_one_cue_per_line(tmp_path):
    # srv2 is emitted word-by-word: only elements without append="1" open a
    # caption line. Reading each element as its own cue yields single-word
    # blocks, and deduplicating those against the running tail deletes every
    # genuine repetition.
    path = tmp_path / "abc.en.srv2"
    path.write_text(SRV2_ALL, encoding="utf-8")

    cues = read_cues(path, SubtitleFormat.SRV2)

    assert len(cues) == 3
    assert cues[0].text == "We are no strangers to love You know the rules"
    assert cues[1].text == "You know the rules and so do I"
    assert cues[2].text == "A full commitment is what I am thinking of"


def test_srv2_keeps_repeated_words_inside_a_line(tmp_path):
    path = tmp_path / "abc.en.srv2"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8" ?><timedtext>'
        '<text t="0" d="1000">the model is</text>'
        '<text t="10" d="990" append="1"> is good</text>'
        '<text t="2000" d="1000">of of the</text>'
        '<text t="2010" d="990" append="1"> the</text>'
        "</timedtext>",
        encoding="utf-8",
    )

    text = clean_cues(path, SubtitleFormat.SRV2)

    assert text == "the model is is good of of the the"
