from __future__ import annotations

import json
from pathlib import Path

import pytest

from salin import cli
from salin.error import (
    RateLimitedError,
    SubtitleDownloadError,
    TranscriptUnavailableError,
    VideoUnavailableError,
)
from salin.shared.models import (
    DownloadStatus,
    LangCode,
    LangCodeRequested,
    LangCodeResolved,
    SubtitleAvailability,
    SubtitleFile,
    SubtitleFormat,
    SubtitleResult,
    SubtitleSource,
    UrlStr,
    VideoId,
)
from salin.transcript import FetchedTranscript, TranscriptSnippet

URL = "https://www.youtube.com/watch?v=abc123"


class FakeSalin:
    """Stand-in for ``Salin`` that records constructor and call arguments."""

    def __init__(self) -> None:
        self.kwargs: dict | None = None
        self.inspect_map: dict[str, object] = {}
        self.fetch_map: dict[str, object] = {}
        self.download_results: list[SubtitleResult] = []
        self.download_kwargs: dict | None = None
        self.download_urls: list[str] = []

    def inspect(self, url: str) -> SubtitleAvailability:
        return _resolve(self.inspect_map, url)

    def fetch(self, url: str) -> FetchedTranscript:
        return _resolve(self.fetch_map, url)

    def download_many(self, urls, **kwargs):
        self.download_kwargs = kwargs
        self.download_urls = list(urls)
        yield from self.download_results


def _resolve(mapping: dict[str, object], url: str):
    value = mapping[url]
    if isinstance(value, BaseException):
        raise value
    return value


@pytest.fixture
def fake(monkeypatch) -> FakeSalin:
    instance = FakeSalin()

    def factory(**kwargs):
        instance.kwargs = kwargs
        return instance

    monkeypatch.setattr(cli, "Salin", factory)
    return instance


def availability(
    url: str = URL,
    video_id: str = "abc123",
    title: str = "Example",
    *,
    manual: dict[str, set[str]] | None = None,
    auto: dict[str, set[str]] | None = None,
) -> SubtitleAvailability:
    manual = manual if manual is not None else {"en": {"vtt", "srt"}}
    auto = auto if auto is not None else {"de": {"vtt"}}
    return SubtitleAvailability(
        url=UrlStr(url),
        video_id=VideoId(video_id),
        title=title,
        manual=frozenset(LangCode(code) for code in manual),
        auto=frozenset(LangCode(code) for code in auto),
        manual_formats={
            LangCode(code): frozenset(fmts) for code, fmts in manual.items()
        },
        auto_formats={LangCode(code): frozenset(fmts) for code, fmts in auto.items()},
    )


def transcript(
    video_id: str = "abc123",
    *,
    language: str = "English",
    language_code: str = "en",
    generated: bool = False,
) -> FetchedTranscript:
    return FetchedTranscript(
        snippets=[
            TranscriptSnippet(text="Hello world", start=1.36, duration=1.68),
            TranscriptSnippet(text="Second line.", start=3.04, duration=2.96),
        ],
        video_id=video_id,
        language=language,
        language_code=language_code,
        is_generated=generated,
    )


def subtitle_file(
    *,
    status: DownloadStatus = DownloadStatus.OK,
    path: Path | None = Path("salin_downloads/abc123.en.vtt"),
    error: str | None = None,
    retry_after: int | None = None,
) -> SubtitleFile:
    return SubtitleFile(
        requested=LangCodeRequested("en"),
        resolved=LangCodeResolved("en"),
        source=SubtitleSource.MANUAL,
        status=status,
        sub_path=path if status == DownloadStatus.OK else None,
        format=SubtitleFormat.VTT if path is not None else None,
        error=error,
        retry_after=retry_after,
    )


def subtitle_result(*subs: SubtitleFile, video_id: str = "abc123") -> SubtitleResult:
    return SubtitleResult(
        url=UrlStr(URL),
        video_id=VideoId(video_id),
        title="Example",
        subtitles=subs or (subtitle_file(),),
    )


def run(*argv: str) -> int:
    return cli.main(list(argv))


# --- parser and entry points -------------------------------------------------


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        run("--version")
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("salin ")


def test_missing_command_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        run()
    assert exc.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_unknown_command_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        run("nope")
    assert exc.value.code == 2


def test_help_points_to_the_cli_guide(capsys):
    with pytest.raises(SystemExit) as exc:
        run("--help")
    assert exc.value.code == 0
    assert "CLI.md" in capsys.readouterr().out


def test_python_dash_m_runs_the_same_entry_point():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "salin", "--version"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.startswith("salin ")


# --- inspect -----------------------------------------------------------------


def test_inspect_human_output(fake, capsys):
    fake.inspect_map[URL] = availability()
    assert run("inspect", URL) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Example (abc123)" in out
    assert "manual: en" in out
    assert "  en: srt, vtt" in out


def test_inspect_json_single_video(fake, capsys):
    fake.inspect_map[URL] = availability()
    assert run("inspect", URL, "--json") == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["video_id"] == "abc123"
    assert payload["manual"] == ["en"]
    assert payload["manual_formats"]["en"] == ["srt", "vtt"]


def test_inspect_json_multiple_videos_is_a_list(fake, capsys):
    other = "https://www.youtube.com/watch?v=def456"
    fake.inspect_map[URL] = availability()
    fake.inspect_map[other] = availability(url=other, video_id="def456")
    assert run("inspect", URL, other, "--json") == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert [item["video_id"] for item in payload] == ["abc123", "def456"]


def test_inspect_failure_json_and_exit_code(fake, capsys):
    fake.inspect_map[URL] = VideoUnavailableError("private video")
    assert run("inspect", URL, "--json") == cli.EXIT_FAILURE
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "ok": False,
        "url": URL,
        "error": "private video",
        "error_class": "VideoUnavailableError",
    }
    assert "salin: " in captured.err


def test_inspect_rate_limit_exit_code(fake, capsys):
    fake.inspect_map[URL] = RateLimitedError("429", retry_after=30)
    assert run("inspect", URL) == cli.EXIT_RATE_LIMITED
    assert "429" in capsys.readouterr().err


def test_inspect_partial_batch_exits_one(fake, capsys):
    other = "https://www.youtube.com/watch?v=def456"
    fake.inspect_map[URL] = availability()
    fake.inspect_map[other] = SubtitleDownloadError("boom")
    assert run("inspect", URL, other) == cli.EXIT_FAILURE
    assert "Example" in capsys.readouterr().out


def test_inspect_does_not_default_languages(fake):
    fake.inspect_map[URL] = availability()
    assert run("inspect", URL) == cli.EXIT_OK
    assert fake.kwargs is not None
    assert fake.kwargs["languages"] is None


# --- fetch -------------------------------------------------------------------


def test_fetch_text_default_language(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert run("fetch", URL) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "Hello world Second line."
    assert fake.kwargs is not None
    assert fake.kwargs["languages"] == ["en"]


def test_fetch_languages_are_flattened(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert run("fetch", URL, "-l", "en,de", "-l", "fr") == cli.EXIT_OK
    assert fake.kwargs is not None
    assert fake.kwargs["languages"] == ["en", "de", "fr"]
    assert fake.kwargs["language_match"] is None
    assert fake.kwargs["source_policy"] is None


def test_fetch_passes_language_options(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert (
        run(
            "fetch",
            URL,
            "--match",
            "exact",
            "--source",
            "auto_only",
            "--proxy",
            "socks5://localhost:1080",
        )
        == cli.EXIT_OK
    )
    assert fake.kwargs is not None
    assert fake.kwargs["language_match"] == "exact"
    assert fake.kwargs["source_policy"] == "auto_only"
    assert fake.kwargs["proxy"] == "socks5://localhost:1080"


def test_fetch_json_schema(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert run("fetch", URL, "--format", "json") == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["video_id"] == "abc123"
    assert payload["language"] == "English"
    assert payload["language_code"] == "en"
    assert payload["is_generated"] is False
    assert payload["snippets"] == [
        {"text": "Hello world", "start": 1.36, "duration": 1.68},
        {"text": "Second line.", "start": 3.04, "duration": 2.96},
    ]


def test_fetch_jsonl_includes_ok_and_errors(fake, capsys):
    other = "https://www.youtube.com/watch?v=def456"
    fake.fetch_map[URL] = transcript()
    fake.fetch_map[other] = TranscriptUnavailableError("def456", "no captions")
    assert run("fetch", URL, other, "--format", "jsonl") == cli.EXIT_FAILURE
    lines = capsys.readouterr().out.strip().splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["ok"] is True
    assert records[0]["url"] == URL
    assert records[1] == {
        "ok": False,
        "url": other,
        "error": "no captions",
        "error_class": "TranscriptUnavailableError",
    }


def test_fetch_srt_and_vtt_timestamps(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert run("fetch", URL, "--format", "srt") == cli.EXIT_OK
    srt = capsys.readouterr().out
    assert srt.startswith("1\n00:00:01,360 --> 00:00:03,040\nHello world")
    assert "2\n00:00:03,040 --> 00:00:06,000\nSecond line." in srt

    assert run("fetch", URL, "--format", "vtt") == cli.EXIT_OK
    vtt = capsys.readouterr().out
    assert vtt.startswith("WEBVTT\n\n00:00:01.360 --> 00:00:03.040")


def test_fetch_writes_output_file(fake, tmp_path, capsys):
    fake.fetch_map[URL] = transcript()
    destination = tmp_path / "out" / "abc.txt"
    assert run("fetch", URL, "--out", str(destination)) == cli.EXIT_OK
    assert destination.read_text(encoding="utf-8").strip() == (
        "Hello world Second line."
    )
    assert capsys.readouterr().out == ""


def test_fetch_reads_url_file_and_skips_comments(fake, tmp_path, capsys):
    other = "https://www.youtube.com/watch?v=def456"
    fake.fetch_map[URL] = transcript()
    fake.fetch_map[other] = transcript(video_id="def456")
    id_file = tmp_path / "ids.txt"
    id_file.write_text(f"# comment\n{URL}\n\n{other}\n", encoding="utf-8")
    assert run("fetch", "--input", str(id_file), "--format", "jsonl") == cli.EXIT_OK
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [record["video_id"] for record in records] == ["abc123", "def456"]


def test_fetch_missing_input_file_is_failure(capsys):
    assert run("fetch", "--input", "does-not-exist.txt") == cli.EXIT_FAILURE
    assert "cannot read" in capsys.readouterr().err


def test_fetch_requires_a_url(capsys):
    assert run("fetch", "--format", "text") == cli.EXIT_USAGE
    assert "at least one URL" in capsys.readouterr().err


def test_fetch_single_video_formats_reject_batches(capsys):
    other = "https://www.youtube.com/watch?v=def456"
    for output_format in ("json", "srt", "vtt"):
        assert run("fetch", URL, other, "--format", output_format) == cli.EXIT_USAGE
    assert "accepts one URL" in capsys.readouterr().err


def test_fetch_all_unavailable_is_exit_four(fake, capsys):
    fake.fetch_map[URL] = TranscriptUnavailableError("abc123", "no captions")
    assert run("fetch", URL) == cli.EXIT_NO_TRANSCRIPT
    assert "no captions" in capsys.readouterr().err


def test_fetch_rate_limit_is_exit_three(fake, capsys):
    fake.fetch_map[URL] = RateLimitedError("429")
    assert run("fetch", URL) == cli.EXIT_RATE_LIMITED
    assert "429" in capsys.readouterr().err


# --- download ----------------------------------------------------------------


def test_download_prints_paths(fake, capsys):
    fake.download_results.append(subtitle_result())
    assert run("download", URL) == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == str(Path("salin_downloads/abc123.en.vtt"))
    assert fake.download_kwargs is not None
    assert fake.download_kwargs["max_workers"] == 1
    assert fake.download_kwargs["subtitle_format"] == "vtt"
    assert fake.download_kwargs["output_dir"] is None
    assert fake.download_urls == [URL]


def test_download_passes_format_and_workers(fake, capsys):
    fake.download_results.append(subtitle_result())
    assert (
        run(
            "download",
            URL,
            "--subtitle-format",
            "srt",
            "--workers",
            "3",
            "--output-dir",
            "subs",
        )
        == cli.EXIT_OK
    )
    assert fake.download_kwargs is not None
    assert fake.download_kwargs["max_workers"] == 3
    assert fake.download_kwargs["subtitle_format"] == "srt"
    assert str(fake.download_kwargs["output_dir"]) == "subs"


def test_download_jsonl_schema(fake, capsys):
    fake.download_results.append(subtitle_result())
    assert run("download", URL, "--json") == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["video_id"] == "abc123"
    assert payload["rate_limited"] is False
    assert payload["subtitles"][0] == {
        "requested": "en",
        "resolved": "en",
        "source": "manual",
        "status": "ok",
        "path": str(Path("salin_downloads/abc123.en.vtt")),
        "format": "vtt",
        "error": None,
        "retry_after": None,
    }


def test_download_missing_subtitle_is_exit_four(fake, capsys):
    fake.download_results.append(
        subtitle_result(subtitle_file(status=DownloadStatus.UNAVAILABLE))
    )
    assert run("download", URL) == cli.EXIT_NO_TRANSCRIPT
    assert "en: unavailable" in capsys.readouterr().err


def test_download_rate_limit_is_exit_three(fake, capsys):
    fake.download_results.append(
        subtitle_result(
            subtitle_file(
                status=DownloadStatus.RATE_LIMITED,
                error="429",
                retry_after=42,
            )
        )
    )
    assert run("download", URL) == cli.EXIT_RATE_LIMITED
    assert "retry after 42s" in capsys.readouterr().err


def test_download_partial_batch_exits_one(fake, capsys):
    other = "https://www.youtube.com/watch?v=def456"
    fake.download_results.extend(
        [
            subtitle_result(),
            subtitle_result(
                subtitle_file(status=DownloadStatus.UNAVAILABLE), video_id="def456"
            ),
        ]
    )
    assert run("download", URL, other) == cli.EXIT_FAILURE
    out = capsys.readouterr().out
    assert str(Path("salin_downloads/abc123.en.vtt")) in out


def test_download_partial_result_is_counted_once(fake, capsys):
    fake.download_results.append(
        subtitle_result(
            subtitle_file(),
            subtitle_file(status=DownloadStatus.UNAVAILABLE),
        )
    )
    assert run("download", URL) == cli.EXIT_FAILURE
    assert str(Path("salin_downloads/abc123.en.vtt")) in capsys.readouterr().out


def test_download_workers_must_be_positive(capsys):
    assert run("download", URL, "--workers", "0") == cli.EXIT_USAGE
    assert "--workers" in capsys.readouterr().err


def test_download_rejects_unknown_subtitle_format(capsys):
    with pytest.raises(SystemExit) as exc:
        run("download", URL, "--subtitle-format", "wav")
    assert exc.value.code == cli.EXIT_USAGE


# --- clean -------------------------------------------------------------------

VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello world.\n"


def test_clean_writes_txt_next_to_source(tmp_path, capsys):
    source = tmp_path / "abc.en.vtt"
    source.write_text(VTT, encoding="utf-8")
    assert run("clean", str(source)) == cli.EXIT_OK
    destination = tmp_path / "abc.en.txt"
    assert destination.exists()
    assert "Hello world." in destination.read_text(encoding="utf-8")
    assert str(destination) in capsys.readouterr().out


def test_clean_output_dir_and_recursive(tmp_path):
    nested = tmp_path / "subs" / "nested"
    nested.mkdir(parents=True)
    (nested / "abc.vtt").write_text(VTT, encoding="utf-8")
    output = tmp_path / "text"
    assert (
        run(
            "clean",
            str(tmp_path / "subs"),
            "--recursive",
            "--output-dir",
            str(output),
        )
        == cli.EXIT_OK
    )
    assert (output / "abc.txt").exists()


def test_clean_skips_existing(tmp_path, capsys):
    source = tmp_path / "abc.vtt"
    source.write_text(VTT, encoding="utf-8")
    destination = tmp_path / "abc.txt"
    destination.write_text("keep me\n", encoding="utf-8")
    assert run("clean", str(source), "--skip-existing") == cli.EXIT_OK
    assert destination.read_text(encoding="utf-8") == "keep me\n"
    assert capsys.readouterr().out == ""


def test_clean_missing_path_is_failure(tmp_path, capsys):
    assert run("clean", str(tmp_path / "nope.vtt")) == cli.EXIT_FAILURE
    assert "no such file" in capsys.readouterr().err


def test_clean_directory_without_subtitles_is_failure(tmp_path, capsys):
    assert run("clean", str(tmp_path)) == cli.EXIT_FAILURE
    assert "no subtitle files" in capsys.readouterr().err


def test_clean_unsupported_file_reports_error(tmp_path, capsys):
    source = tmp_path / "song.wav"
    source.write_text("not a subtitle", encoding="utf-8")
    assert run("clean", str(source)) == cli.EXIT_FAILURE
    assert "song.wav" in capsys.readouterr().err


# --- doctor ------------------------------------------------------------------


def test_doctor_prints_versions_without_check(fake, capsys):
    assert run("doctor") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("salin ")
    assert "Python " in out
    assert "yt-dlp " in out


def test_doctor_smoke_test_ok(fake, capsys):
    fake.fetch_map[URL] = transcript()
    assert run("doctor", "--check", URL) == cli.EXIT_OK
    assert "smoke test ok: 2 snippets (en" in capsys.readouterr().out


def test_doctor_check_accepts_language_options(fake, capsys):
    fake.fetch_map[URL] = transcript(language_code="de", language="Deutsch")
    assert (
        run(
            "doctor",
            "--check",
            URL,
            "-l",
            "de",
            "--match",
            "exact",
            "--source",
            "manual_only",
        )
        == cli.EXIT_OK
    )
    assert fake.kwargs is not None
    assert fake.kwargs["languages"] == ["de"]
    assert fake.kwargs["language_match"] == "exact"
    assert fake.kwargs["source_policy"] == "manual_only"
    assert "(de, generated=False)" in capsys.readouterr().out


def test_doctor_smoke_test_exit_codes(fake, capsys):
    cases = [
        (TranscriptUnavailableError("abc123", "none"), cli.EXIT_NO_TRANSCRIPT),
        (RateLimitedError("429"), cli.EXIT_RATE_LIMITED),
        (SubtitleDownloadError("boom"), cli.EXIT_FAILURE),
    ]
    for exc, expected in cases:
        fake.fetch_map[URL] = exc
        assert run("doctor", "--check", URL) == expected
    assert "no transcript" in capsys.readouterr().err


# --- exit code table ---------------------------------------------------------


@pytest.mark.parametrize(
    ("ok", "failed", "no_transcript", "rate_limited", "expected"),
    [
        (1, 0, 0, False, cli.EXIT_OK),
        (0, 0, 1, False, cli.EXIT_NO_TRANSCRIPT),
        (0, 1, 0, False, cli.EXIT_FAILURE),
        (1, 0, 1, False, cli.EXIT_FAILURE),
        (1, 0, 0, True, cli.EXIT_RATE_LIMITED),
        (0, 0, 0, False, cli.EXIT_FAILURE),
    ],
)
def test_exit_code_table(ok, failed, no_transcript, rate_limited, expected):
    assert (
        cli._exit_code(
            ok=ok,
            failed=failed,
            no_transcript=no_transcript,
            rate_limited=rate_limited,
        )
        == expected
    )
