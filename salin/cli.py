"""Command-line interface for Salin.

The CLI is a thin wrapper over :class:`salin.client.Salin`. Every command maps
to one library call, so the exit codes are the only behaviour that is unique to
this module:

===== ==========================================================
code  meaning
===== ==========================================================
0     every requested item succeeded
1     at least one item failed, or the batch was partial
2     invalid usage
3     YouTube rate-limited the request
4     no transcript was available for the requested language
===== ==========================================================
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from salin import __version__
from salin.cleaner import clean_cues
from salin.client import Salin
from salin.error import (
    RateLimitedError,
    SalinError,
    TranscriptUnavailableError,
    VideoUnavailableError,
)
from salin.shared.models import (
    DownloadStatus,
    LanguageMatch,
    SubtitleAvailability,
    SubtitleFormat,
    SubtitleResult,
    SubtitleSourcePolicy,
)
from salin.transcript import FetchedTranscript

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_RATE_LIMITED = 3
EXIT_NO_TRANSCRIPT = 4

SUBTITLE_FORMATS = tuple(fmt.value for fmt in SubtitleFormat)
OUTPUT_FORMATS = ("text", "json", "jsonl", "srt", "vtt")
MISSING_STATUSES = frozenset({DownloadStatus.UNAVAILABLE, DownloadStatus.MISSING})


class _CliExit(Exception):
    """Internal control flow for a known exit code, kept out of argparse."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="salin",
        description="Inspect, fetch, download, and clean YouTube subtitle tracks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Full guide: https://github.com/krvspacetime/salin/blob/main/CLI.md\n"
            "Run 'salin COMMAND --help' for command options."
        ),
    )
    parser.add_argument("--version", action="version", version=f"salin {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    net = argparse.ArgumentParser(add_help=False)
    net.add_argument(
        "--cookies-from-browser",
        metavar="SPEC",
        help="read cookies from a browser (yt-dlp syntax, e.g. 'firefox:default')",
    )
    net.add_argument(
        "--cookiefile", type=Path, metavar="FILE", help="Netscape cookies.txt"
    )
    net.add_argument("--proxy", metavar="URL", help="HTTP or SOCKS proxy URL")

    request = argparse.ArgumentParser(add_help=False, parents=[net])
    request.add_argument(
        "-l",
        "--language",
        action="append",
        metavar="LANG",
        help="requested language, repeatable or comma-separated (default: en)",
    )
    request.add_argument(
        "--match",
        choices=[match.value for match in LanguageMatch],
        help="language matching (default: regional)",
    )
    request.add_argument(
        "--source",
        choices=[policy.value for policy in SubtitleSourcePolicy],
        help="manual vs automatic track policy (default: manual_then_auto)",
    )

    inspect = subparsers.add_parser(
        "inspect", parents=[net], help="show the tracks a video offers"
    )
    inspect.add_argument("urls", nargs="+", metavar="URL")
    inspect.add_argument("--json", action="store_true", help="print JSON")
    inspect.set_defaults(func=cmd_inspect)

    fetch = subparsers.add_parser(
        "fetch", parents=[request], help="fetch transcripts in memory"
    )
    fetch.add_argument("urls", nargs="*", metavar="URL")
    fetch.add_argument(
        "-i", "--input", type=Path, metavar="FILE", help="read URLs from a file"
    )
    fetch.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="text",
        help="output format (default: text)",
    )
    fetch.add_argument("--out", type=Path, metavar="FILE", help="write to a file")
    fetch.set_defaults(func=cmd_fetch)

    download = subparsers.add_parser(
        "download", parents=[request], help="download subtitle files"
    )
    download.add_argument("urls", nargs="*", metavar="URL")
    download.add_argument(
        "-i", "--input", type=Path, metavar="FILE", help="read URLs from a file"
    )
    download.add_argument(
        "-f",
        "--subtitle-format",
        choices=SUBTITLE_FORMATS,
        default=SubtitleFormat.VTT.value,
        help="subtitle file format (default: vtt)",
    )
    download.add_argument(
        "-o", "--output-dir", type=Path, metavar="DIR", help="destination directory"
    )
    download.add_argument(
        "-w",
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="parallel downloads (default: 1)",
    )
    download.add_argument(
        "--json", action="store_true", help="print one JSON object per video"
    )
    download.set_defaults(func=cmd_download)

    clean = subparsers.add_parser(
        "clean", help="turn subtitle files into plain-text transcripts"
    )
    clean.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    clean.add_argument(
        "-o", "--output-dir", type=Path, metavar="DIR", help="destination directory"
    )
    clean.add_argument(
        "--recursive", action="store_true", help="descend into directories"
    )
    clean.add_argument(
        "--skip-existing", action="store_true", help="keep existing .txt files"
    )
    clean.set_defaults(func=cmd_clean)

    doctor = subparsers.add_parser(
        "doctor",
        parents=[request],
        help="show versions and optionally run a smoke test",
    )
    doctor.add_argument(
        "--check", metavar="URL", help="fetch one URL to test the whole pipeline"
    )
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = getattr(args, "func", None)
    if command is None:  # pragma: no cover - argparse requires a subcommand
        parser.error("missing command")
    try:
        return int(command(args))
    except _CliExit as exc:
        return exc.code
    except KeyboardInterrupt:
        print("salin: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return EXIT_OK


def _usage_error(message: str) -> NoReturn:
    print(f"salin: error: {message}", file=sys.stderr)
    raise _CliExit(EXIT_USAGE)


def _fail(message: str) -> NoReturn:
    print(f"salin: {message}", file=sys.stderr)
    raise _CliExit(EXIT_FAILURE)


def _split_languages(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [
        part.strip() for value in values for part in value.split(",") if part.strip()
    ]


def _client(args: argparse.Namespace, *, need_languages: bool) -> Salin:
    languages = _split_languages(getattr(args, "language", None))
    if need_languages and not languages:
        languages = ["en"]
    return Salin(
        languages=languages or None,
        language_match=getattr(args, "match", None),
        source_policy=getattr(args, "source", None),
        cookies=getattr(args, "cookies_from_browser", None),
        cookiefile=getattr(args, "cookiefile", None),
        proxy=getattr(args, "proxy", None),
    )


def _collect_urls(urls: list[str], input_file: Path | None) -> list[str]:
    collected = list(urls)
    if input_file is not None:
        try:
            lines = input_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            _fail(f"cannot read {input_file}: {exc}")
        for line in lines:
            value = line.strip()
            if value and not value.startswith("#"):
                collected.append(value)
    if not collected:
        _usage_error("provide at least one URL or --input FILE")
    return collected


def _write(text: str, path: Path | None) -> None:
    if path is None:
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _error_record(url: str, exc: BaseException) -> dict[str, Any]:
    return {
        "ok": False,
        "url": url,
        "error": str(exc),
        "error_class": type(exc).__name__,
    }


def _exit_code(
    *,
    ok: int,
    failed: int,
    no_transcript: int,
    rate_limited: bool,
) -> int:
    if rate_limited:
        return EXIT_RATE_LIMITED
    if failed:
        return EXIT_FAILURE
    if ok and no_transcript:
        return EXIT_FAILURE
    if ok:
        return EXIT_OK
    if no_transcript:
        return EXIT_NO_TRANSCRIPT
    return EXIT_FAILURE


def _availability_dict(availability: SubtitleAvailability) -> dict[str, Any]:
    return {
        "ok": True,
        "url": str(availability.url),
        "video_id": str(availability.video_id),
        "title": availability.title,
        "manual": sorted(availability.manual),
        "auto": sorted(availability.auto),
        "manual_formats": {
            code: sorted(formats)
            for code, formats in availability.manual_formats.items()
        },
        "auto_formats": {
            code: sorted(formats) for code, formats in availability.auto_formats.items()
        },
    }


def _print_availability(availability: SubtitleAvailability) -> None:
    print(f"{availability.title} ({availability.video_id})")
    for label, codes, formats in (
        ("manual", availability.manual, availability.manual_formats),
        ("auto", availability.auto, availability.auto_formats),
    ):
        print(f"{label}: {', '.join(sorted(codes)) or '-'}")
        for code in sorted(codes):
            print(f"  {code}: {', '.join(sorted(formats.get(code, ()))) or '-'}")


def cmd_inspect(args: argparse.Namespace) -> int:
    client = _client(args, need_languages=False)
    records: list[dict[str, Any]] = []
    ok = 0
    failed = 0
    rate_limited = False

    for url in args.urls:
        try:
            availability = client.inspect(url)
        except RateLimitedError as exc:
            rate_limited = True
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        except (VideoUnavailableError, TranscriptUnavailableError) as exc:
            failed += 1
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        except (SalinError, OSError) as exc:
            failed += 1
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        else:
            ok += 1
            records.append(_availability_dict(availability))
            if not args.json:
                _print_availability(availability)

    if args.json:
        payload: Any = records[0] if len(records) == 1 else records
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return _exit_code(ok=ok, failed=failed, no_transcript=0, rate_limited=rate_limited)


def _transcript_dict(transcript: FetchedTranscript) -> dict[str, Any]:
    return {
        "video_id": str(transcript.video_id),
        "language": transcript.language,
        "language_code": str(transcript.language_code),
        "is_generated": transcript.is_generated,
        "snippets": transcript.to_raw_data(),
    }


def _timestamp(seconds: float, *, srt: bool) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _transcript_srt(transcript: FetchedTranscript) -> str:
    blocks = []
    for index, snippet in enumerate(transcript, start=1):
        text = " ".join(snippet.text.split())
        start = _timestamp(snippet.start, srt=True)
        end = _timestamp(snippet.start + snippet.duration, srt=True)
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks)


def _transcript_vtt(transcript: FetchedTranscript) -> str:
    blocks = []
    for snippet in transcript:
        text = " ".join(snippet.text.split())
        start = _timestamp(snippet.start, srt=False)
        end = _timestamp(snippet.start + snippet.duration, srt=False)
        blocks.append(f"{start} --> {end}\n{text}")
    return "WEBVTT\n\n" + "\n\n".join(blocks)


def _render_transcript(transcript: FetchedTranscript, output_format: str) -> str:
    if output_format == "text":
        return transcript.text
    if output_format == "json":
        return json.dumps(_transcript_dict(transcript), ensure_ascii=False, indent=2)
    if output_format == "srt":
        return _transcript_srt(transcript)
    if output_format == "vtt":
        return _transcript_vtt(transcript)
    raise AssertionError(f"unhandled output format: {output_format}")


def cmd_fetch(args: argparse.Namespace) -> int:
    urls = _collect_urls(args.urls, args.input)
    if args.format in ("srt", "vtt", "json") and len(urls) > 1:
        _usage_error(f"--format {args.format} accepts one URL; use jsonl for many")

    client = _client(args, need_languages=True)
    rendered: list[str] = []
    records: list[dict[str, Any]] = []
    ok = 0
    failed = 0
    no_transcript = 0
    rate_limited = False

    for url in urls:
        try:
            transcript = client.fetch(url)
        except RateLimitedError as exc:
            rate_limited = True
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        except (TranscriptUnavailableError, VideoUnavailableError) as exc:
            no_transcript += 1
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        except (SalinError, OSError) as exc:
            failed += 1
            records.append(_error_record(url, exc))
            print(f"salin: {url}: {exc}", file=sys.stderr)
        else:
            ok += 1
            if args.format == "jsonl":
                records.append({"ok": True, "url": url, **_transcript_dict(transcript)})
            else:
                rendered.append(_render_transcript(transcript, args.format))

    if args.format == "jsonl":
        output = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    elif args.format == "text":
        output = "\n\n".join(rendered)
    else:
        output = "\n".join(rendered)

    if output:
        _write(output, args.out)

    return _exit_code(
        ok=ok, failed=failed, no_transcript=no_transcript, rate_limited=rate_limited
    )


def _subtitle_dict(result: SubtitleResult) -> dict[str, Any]:
    return {
        "url": str(result.url),
        "video_id": str(result.video_id),
        "title": result.title,
        "ok": bool(result.ok_subs),
        "rate_limited": result.is_rate_limited,
        "retry_after": result.retry_after,
        "subtitles": [
            {
                "requested": str(sub.requested),
                "resolved": str(sub.resolved) if sub.resolved else None,
                "source": sub.source.value if sub.source else None,
                "status": sub.status.value,
                "path": str(sub.sub_path) if sub.sub_path else None,
                "format": sub.format.value if sub.format else None,
                "error": sub.error,
                "retry_after": sub.retry_after,
            }
            for sub in result.subtitles
        ],
    }


def _classify_download(result: SubtitleResult) -> str:
    """One label per video: ok, partial, no_transcript, or error."""
    if result.ok_subs:
        return "ok" if len(result.ok_subs) == len(result.subtitles) else "partial"
    statuses = {sub.status for sub in result.subtitles}
    if statuses and statuses <= MISSING_STATUSES:
        return "no_transcript"
    return "error"


def _download_failure_message(result: SubtitleResult) -> str:
    if result.is_rate_limited:
        suffix = f" (retry after {result.retry_after}s)" if result.retry_after else ""
        return f"rate limited{suffix}"
    return "; ".join(
        f"{sub.requested}: {sub.error or sub.status.value}" for sub in result.subtitles
    )


def cmd_download(args: argparse.Namespace) -> int:
    urls = _collect_urls(args.urls, args.input)
    if args.workers < 1:
        _usage_error("--workers must be at least 1")

    client = _client(args, need_languages=True)
    ok = 0
    failed = 0
    no_transcript = 0
    rate_limited = False

    results = client.download_many(
        urls,
        max_workers=args.workers,
        output_dir=args.output_dir,
        subtitle_format=args.subtitle_format,
    )
    for result in results:
        outcome = _classify_download(result)
        if result.is_rate_limited:
            rate_limited = True

        if args.json:
            print(json.dumps(_subtitle_dict(result), ensure_ascii=False))
        elif outcome in ("ok", "partial"):
            for sub in result.ok_subs:
                print(sub.sub_path)

        if outcome == "ok":
            ok += 1
        elif outcome == "partial":
            failed += 1
        elif outcome == "no_transcript":
            no_transcript += 1
        else:
            failed += 1

        if outcome != "ok" and not args.json:
            print(
                f"salin: {result.video_id}: {_download_failure_message(result)}",
                file=sys.stderr,
            )

    return _exit_code(
        ok=ok, failed=failed, no_transcript=no_transcript, rate_limited=rate_limited
    )


def _subtitle_files(paths: list[Path], *, recursive: bool) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            files.extend(
                item
                for item in sorted(iterator)
                if item.is_file()
                and item.suffix.lstrip(".").lower() in SUBTITLE_FORMATS
            )
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    return files


def cmd_clean(args: argparse.Namespace) -> int:
    try:
        files = _subtitle_files(args.paths, recursive=args.recursive)
    except FileNotFoundError as exc:
        _fail(f"no such file or directory: {exc}")

    if not files:
        _fail("no subtitle files found")

    ok = 0
    skipped = 0
    failed = 0
    for path in files:
        destination = (
            args.output_dir / f"{path.stem}.txt"
            if args.output_dir
            else path.with_suffix(".txt")
        )
        if args.skip_existing and destination.exists():
            skipped += 1
            continue
        try:
            subtitle_format = SubtitleFormat(path.suffix.lstrip(".").lower())
            text = clean_cues(path, subtitle_format)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text + "\n", encoding="utf-8")
        except (OSError, ValueError) as exc:
            failed += 1
            print(f"salin: {path}: {exc}", file=sys.stderr)
            continue
        ok += 1
        print(destination)

    if failed:
        return EXIT_FAILURE
    return EXIT_OK if ok or skipped else EXIT_FAILURE


def cmd_doctor(args: argparse.Namespace) -> int:
    from yt_dlp.version import __version__ as yt_dlp_version

    print(f"salin {__version__}")
    print(f"Python {platform.python_version()} ({platform.platform()})")
    print(f"yt-dlp {yt_dlp_version}")

    if not args.check:
        return EXIT_OK

    client = _client(args, need_languages=True)
    try:
        transcript = client.fetch(args.check)
    except RateLimitedError as exc:
        print(f"salin: smoke test rate limited: {exc}", file=sys.stderr)
        return EXIT_RATE_LIMITED
    except (TranscriptUnavailableError, VideoUnavailableError) as exc:
        print(f"salin: smoke test found no transcript: {exc}", file=sys.stderr)
        return EXIT_NO_TRANSCRIPT
    except (SalinError, OSError) as exc:
        print(f"salin: smoke test failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    print(
        f"smoke test ok: {len(transcript)} snippets "
        f"({transcript.language_code}, generated={transcript.is_generated})"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
