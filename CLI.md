# Salin command line

`salin` is the command-line interface for the [Salin](README.md) library. It
exposes the same operations: inspect a video's tracks, fetch a transcript into
memory, download subtitle files, clean local files, and check an installation.

## Install

```bash
pip install salin
salin --version
```

Requires Python 3.12 or newer. Installing the package also installs `yt-dlp`,
which does the extraction and downloads.

If `salin` is not on `PATH`, run the same entry point as a module:

```bash
python -m salin --version
python -m salin fetch dQw4w9WgXcQ
```

## Commands at a glance

| Command    | What it does                                      | Contacts YouTube |
| ---------- | ------------------------------------------------- | ---------------- |
| `inspect`  | List manual and automatic tracks, with formats    | yes              |
| `fetch`    | Fetch transcripts and print them or write a file  | yes              |
| `download` | Write subtitle files to disk                      | yes              |
| `clean`    | Turn subtitle files into plain-text transcripts   | no               |
| `doctor`   | Print versions, optionally run a fetch smoke test | with `--check`   |

```text
salin inspect URL [URL ...] [--json] [network options]
salin fetch   [URL ...] [-i FILE] [language options] [--format FMT] [--out FILE]
salin download [URL ...] [-i FILE] [language options] [-f FMT] [-o DIR] [-w N] [--json]
salin clean   PATH [PATH ...] [-o DIR] [--recursive] [--skip-existing]
salin doctor  [language options] [--check URL]
```

Run `salin COMMAND --help` for the option list of one command, or `salin --help`
for the command list.

## Shared conventions

### URLs and video IDs

A URL can be any of these forms:

```text
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://youtu.be/dQw4w9WgXcQ
dQw4w9WgXcQ
```

Pass one URL per argument. The CLI does not expand playlists or channels; each
URL must resolve to a single video.

### Reading URLs from a file

`fetch` and `download` accept `-i FILE` / `--input FILE`. The file is UTF-8,
one URL or video ID per line. Blank lines are ignored, and lines starting with
`#` are comments. Positional URLs and `--input` can be combined; positional
URLs are processed first.

```bash
# ids.txt
# Videos from the October batch
https://www.youtube.com/watch?v=dQw4w9WgXcQ
9bZkp7q19f0
```

A missing or unreadable input file exits with code `1`. Supplying neither a URL
nor `--input` is a usage error (code `2`).

### Languages

`fetch`, `download`, and `doctor --check` request English by default. Select
languages with `-l` / `--language`; repeat the flag or use commas:

```bash
salin fetch URL -l en
salin fetch URL -l en -l de -l ja
salin fetch URL -l en,de,ja
```

Order is preserved. Each requested language produces its own subtitle file for
`download`; `fetch` returns the first track that resolves.

Language resolution is controlled by two options:

| Option             | Values                                                            | Default             |
| ------------------ | ----------------------------------------------------------------- | ------------------- |
| `--match`          | `exact`, `regional`                                               | `regional`          |
| `--source`         | `manual_only`, `auto_only`, `manual_then_auto`, `auto_then_manual` | `manual_then_auto`  |

`--match exact` only accepts the requested code itself; `regional` may resolve
to variants such as `en-US`, `en-GB`, or `en-orig`. The source policy decides
whether manual or automatic tracks are preferred. See
[Resolving languages](README.md#resolving-languages) for the full rules.

`inspect` does not take language options because it lists everything available.

### Cookies and proxies

Every command that contacts YouTube accepts:

```bash
--cookies-from-browser SPEC    # yt-dlp browser syntax, e.g. firefox:default
--cookiefile FILE              # Netscape cookies.txt
--proxy URL                    # http://, https://, socks5://
```

```bash
salin download URL --cookies-from-browser firefox:default
salin download URL --cookiefile cookies.txt
salin download URL --proxy socks5://127.0.0.1:1080
```

Cookies are opt-in because they send your logged-in browser session to YouTube.
Prefer `--cookiefile` when you do not want the CLI reading a browser profile.
See [Cookies and proxies](README.md#cookies-and-proxies) in the library docs.

### Standard output and errors

Primary output goes to stdout: caption text, JSON/JSONL, or the paths of written
files. Diagnostics go to stderr, prefixed with `salin:`. This means stdout stays
clean enough to pipe:

```bash
salin fetch dQw4w9WgXcQ | wc -w
salin fetch -i ids.txt --format jsonl | jq -r 'select(.ok) | .video_id'
```

`--out FILE` writes the primary output to a UTF-8 file instead and creates
missing parent directories. A trailing newline is added when one is missing.

## inspect

```text
salin inspect URL [URL ...] [--json]
```

`inspect` extracts metadata only. It does not fetch caption bytes and does not
write files. The human-readable form lists the video title and ID, then the
manual and automatic tracks with the formats each one offers. Codes and formats
are sorted.

```text
$ salin inspect dQw4w9WgXcQ
Example Video (dQw4w9WgXcQ)
manual: de, en
  de: json3, srt, vtt
  en: json3, srt, vtt
auto: en-orig
  en-orig: vtt
```

Multiple URLs are separated by a blank line. If one video fails, the others are
still inspected and the failure is printed to stderr.

### JSON schema

For a single URL, `--json` prints one object:

```json
{
  "ok": true,
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "video_id": "dQw4w9WgXcQ",
  "title": "Example Video",
  "manual": ["de", "en"],
  "auto": ["en-orig"],
  "manual_formats": {
    "de": ["json3", "srt", "vtt"],
    "en": ["json3", "srt", "vtt"]
  },
  "auto_formats": {
    "en-orig": ["vtt"]
  }
}
```

For several URLs, it prints an array of those objects. A failed video appears as
an error record in the same array; a single failed URL prints just that error
object:

```json
{
  "ok": false,
  "url": "https://www.youtube.com/watch?v=private",
  "error": "Video unavailable",
  "error_class": "VideoUnavailableError"
}
```

Exit codes: `0` when every video was inspected, `1` when any failed, `3` when a
request was rate-limited. `inspect` never returns `4`.

## fetch

```text
salin fetch [URL ...] [-i FILE] [-l LANG] [--match MODE] [--source POLICY]
            [--format text|json|jsonl|srt|vtt] [--out FILE]
```

`fetch` retrieves a transcript in memory and writes nothing unless `--out` is
given. It is the command to use for piping and for JSON output.

### Output formats

| `--format` | Output                        | Multiple URLs | Notes                                         |
| ---------- | ----------------------------- | ------------- | --------------------------------------------- |
| `text`     | Plain caption text            | yes           | Default. Cues joined with spaces.             |
| `json`     | One object                    | no            | Metadata plus snippets.                       |
| `jsonl`    | One object per line           | yes           | Every video gets a record, including failures. |
| `srt`      | SubRip subtitle file          | no            | Rebuilt from fetched cues.                    |
| `vtt`      | WebVTT subtitle file          | no            | Rebuilt from fetched cues.                    |

`json`, `srt`, and `vtt` describe a single transcript, so they are rejected when
more than one URL is supplied. Use `jsonl` for batches.

`text` is the raw caption text: every snippet's text joined with a single space.
It is not deduplicated. Auto-generated tracks often repeat the tail of one cue
at the start of the next, so overlapping text can appear. For clean prose,
download a file and run `salin clean`; see [Cleaning auto-captions](README.md#cleaning-auto-captions).

For multiple URLs, `text` output joins the transcripts with a blank line and no
headers, so it is not a way to tell videos apart. Use `jsonl` when you need
boundaries.

`srt` and `vtt` are generated from the fetched snippets; they are not the
original caption files. Timestamps use `HH:MM:SS,mmm` for SRT and
`HH:MM:SS.mmm` for VTT, and whitespace inside each cue is collapsed.

### JSON schemas

`--format json` prints one indented object:

```json
{
  "video_id": "dQw4w9WgXcQ",
  "language": "English",
  "language_code": "en",
  "is_generated": false,
  "snippets": [
    {
      "text": "We're no strangers to love",
      "start": 18.64,
      "duration": 3.24
    }
  ]
}
```

`language` is YouTube's display name for the track when available; use
`language_code` as the stable key. `snippets[].start` and `duration` are seconds,
and may be fractional. `is_generated` is `true` for automatic captions. The
single-video object does not include `ok` or `url`; JSONL adds both.

`--format jsonl` prints one compact object per video, in input order. A
successful record adds `ok` and `url` to the object above. Abbreviated to one
snippet:

```json
{"ok": true, "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video_id": "dQw4w9WgXcQ", "language": "English", "language_code": "en", "is_generated": false, "snippets": [...]}
```

A failed video is still one line, with the error instead of transcript fields:

```json
{"ok": false, "url": "https://www.youtube.com/watch?v=private", "error": "Video unavailable", "error_class": "VideoUnavailableError"}
```

Errors are also printed to stderr. stdout remains valid JSONL even when some
videos fail; check each record's `ok` or the process exit code.

### Writing to a file

```bash
salin fetch dQw4w9WgXcQ --format srt --out talk.srt
salin fetch -i ids.txt --format jsonl --out transcripts.jsonl
```

If there is nothing to write (every video failed in `text`/`srt`/`vtt` mode),
the output file is not created. `jsonl` still produces records for failures.

## download

```text
salin download [URL ...] [-i FILE] [-l LANG] [--match MODE] [--source POLICY]
               [-f FORMAT] [-o DIR] [-w N] [--json]
```

`download` writes subtitle files for every requested language. By default they
land in `./salin_downloads`, named:

```text
<video_id>.<resolved_language>.<format>
```

For example, `salin download dQw4w9WgXcQ -f srt -o subs` writes
`subs/dQw4w9WgXcQ.en.srt`. Existing files at that path are overwritten.

### Subtitle formats

`-f` / `--subtitle-format` accepts what YouTube serves:

| Format  | Notes                                       |
| ------- | ------------------------------------------- |
| `vtt`   | Default. WebVTT.                            |
| `srt`   | SubRip.                                     |
| `json3` | YouTube's JSON3 format.                     |
| `srv1`  | YouTube's rolling caption format, version 1. |
| `srv2`  | Version 2.                                   |
| `srv3`  | Version 3.                                   |
| `ttml`  | Timed Text Markup Language.                  |

These are the downloaded formats, not conversions. Use `salin clean` to turn any
of them into plain text. VTT is the only rolling format and its cleaned text can
be slightly longer than the other formats; see
[Cleaning auto-captions](README.md#cleaning-auto-captions).

### Workers

`-w` / `--workers` controls parallel downloads and defaults to `1`
(sequential). Results are printed as each video finishes, so with more than one
worker the file order is completion order, not input order.

```bash
salin download -i ids.txt -l en -l de -w 3 -o subs
```

Three workers is the measured knee for bulk batches; six is faster but its
advantage is not reliable. Workers shorten a batch, they do not make a high
request rate safe. See [How many workers to use](README.md#how-many-workers-to-use)
for the benchmark and for pacing guidance.

### JSON output

`--json` prints one compact object per line (JSONL) for every video, including
failed videos. It replaces the default path output, so no paths are printed in
this mode. With `-w` greater than `1`, objects arrive in completion order.

```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "video_id": "dQw4w9WgXcQ",
  "title": "Example Video",
  "ok": true,
  "rate_limited": false,
  "retry_after": null,
  "subtitles": [
    {
      "requested": "en",
      "resolved": "en",
      "source": "manual",
      "status": "ok",
      "path": "salin_downloads/dQw4w9WgXcQ.en.vtt",
      "format": "vtt",
      "error": null,
      "retry_after": null
    }
  ]
}
```

`ok` is `true` when at least one requested subtitle was written; inspect each
entry for partial results. `retry_after` is the largest `Retry-After` reported
for the video, in seconds, when the server sent one. `source` is `manual`,
`auto`, or `null` when nothing resolved. `path` and `format` are `null` when no
file was written.

Per-subtitle status values:

| Status         | Meaning                                                    |
| -------------- | ---------------------------------------------------------- |
| `ok`           | File written.                                              |
| `missing`      | The video does not list a track for that request.          |
| `unavailable`  | A track exists but YouTube refused or omitted the payload. |
| `rate_limited` | HTTP 429 from the caption endpoint.                        |
| `error`        | Another download or parse failure; see `error`.            |

Without `--json`, successful paths go to stdout and failed videos are summarised
on stderr. A video with one successful language and one missing language is a
partial result: its successful path is printed and the process exits `1`.

## clean

```text
salin clean PATH [PATH ...] [-o DIR] [--recursive] [--skip-existing]
```

`clean` reads subtitle files and writes one `.txt` per input. It merges rolling
caption overlaps, strips timing and display markup, and normalizes whitespace.
It does not contact YouTube.

Recognized extensions:

```text
.vtt  .srt  .json3  .srv1  .srv2  .srv3  .ttml
```

When a path is a directory, only files with those extensions are selected.
`--recursive` descends into subdirectories; without it only the top level is
read. An explicit file is always attempted, so an unsupported extension produces
an error and a nonzero exit.

Output naming:

```text
subs/dQw4w9WgXcQ.en.vtt   ->  subs/dQw4w9WgXcQ.en.txt
subs/dQw4w9WgXcQ.en.vtt   ->  transcripts/dQw4w9WgXcQ.en.txt   (with -o transcripts)
```

Without `-o`, the `.txt` lands next to its source. With `-o`, outputs are written
directly into that directory using the source stem. If two inputs share a stem,
the later file overwrites the earlier one; `--skip-existing` keeps the first.

Each written path is printed to stdout. `--skip-existing` leaves an existing
`.txt` untouched; a skipped file counts as success, not as a failure.

```bash
# one file
salin clean talk.en.srt

# a download directory, including nested files
salin clean subs/ --recursive --output-dir transcripts/

# re-run without overwriting finished transcripts
salin clean subs/ --recursive -o transcripts/ --skip-existing
```

## doctor

```text
salin doctor [language options] [--check URL]
```

Without `--check`, `doctor` prints versions and exits `0`. For example:

```text
salin 0.1.2
Python 3.12.4 (Windows-11-10.0.22631-SP0)
yt-dlp 2026.07.04
```

With `--check URL`, it also fetches one transcript using the normal language and
network options. This tests extraction, the caption endpoint, and cookie/proxy
configuration in one smoke test:

```bash
salin doctor --check dQw4w9WgXcQ
salin doctor --check dQw4w9WgXcQ -l de --cookies-from-browser firefox:default
```

The smoke test prints the snippet count, resolved language code, and whether the
track was auto-generated:

```text
smoke test ok: 42 snippets (en, generated=False)
```

Exit codes for `--check`: `0` success, `1` other failure, `3` rate-limited,
`4` no transcript. Without `--check` it always returns `0`.

## Exit codes

| Code  | Meaning                                                              |
| ----- | -------------------------------------------------------------------- |
| `0`   | Everything requested succeeded.                                     |
| `1`   | At least one item failed, or a batch was partial.                    |
| `2`   | Invalid usage: unknown option, missing command, invalid format, etc. |
| `3`   | YouTube rate-limited at least one request.                           |
| `4`   | No transcript was available for the requested language.              |
| `130` | Interrupted with Ctrl-C.                                             |

Precedence and edge cases:

- Any rate limit in a run returns `3`, even when other videos succeeded. This
  is the signal to stop and retry later.
- A mix of success and failure returns `1`. So does a batch where some videos
  had transcripts and others had none.
- `4` is only returned when nothing succeeded and every failure was a missing
  transcript or an unavailable video. If there was also a generic error, the
  code is `1`.
- `inspect` never returns `4`; it returns `1` for unavailable videos.
- `clean` returns `1` when it could not read or parse a file, or when a
  directory contained no recognized subtitle files.

In a shell, use the code to branch without parsing text:

```bash
salin fetch "$URL" --out transcript.txt
status=$?
case "$status" in
  0) echo "saved" ;;
  3) echo "rate limited; retry later" ;;
  4) echo "no English transcript" ;;
  *) echo "failed with $status" >&2 ;;
esac
```

In Python, `subprocess.run(...).returncode` carries the same values.

## Recipes

### Save one transcript

```bash
salin fetch dQw4w9WgXcQ --out transcript.txt
salin fetch dQw4w9WgXcQ --format srt --out transcript.srt
salin fetch dQw4w9WgXcQ --format json --out transcript.json
```

### Batch transcripts as JSONL

```bash
salin fetch -i ids.txt --format jsonl --out transcripts.jsonl

jq -r 'select(.ok) | [.video_id, .language_code, ([.snippets[].text] | join(" "))] | @tsv' \
  transcripts.jsonl > transcripts.tsv
```

The JSONL file contains failures too, which makes the output auditable.

### Batch download and clean

```bash
salin download -i ids.txt -l en -l de -w 3 -o subs
salin clean subs/ --recursive -o transcripts/
```

`download` writes the chosen subtitle format as served; `clean` then produces
deduplicated `.txt` files.

### Inspect before choosing a language

```bash
salin inspect dQw4w9WgXcQ
salin fetch dQw4w9WgXcQ -l de --source manual_only
```

`inspect` shows which codes exist and whether they are manual or automatic, so
you can choose a code that will resolve.

### Pace a long unattended run

The CLI does not add pauses. For a long list, run smaller chunks or insert a
delay between videos:

```bash
while IFS= read -r id; do
  [ -z "$id" ] && continue
  case "$id" in \#*) continue ;; esac
  salin download "$id" -w 1 -o subs
  sleep 4
done < ids.txt
```

Four seconds between sequential downloads plus the download time keeps a run
below the 11-15 videos/min that completed long benchmark runs without a block.
Raise the pause, not the worker count, when you see exit code `3`.

### Use cookies or a proxy

```bash
salin download URL --cookies-from-browser chrome
salin download URL --cookiefile cookies.txt
salin fetch URL --proxy socks5://127.0.0.1:1080
```

## Troubleshooting

**`salin: command not found`**

The package installed but the script directory is not on `PATH`. Use
`python -m salin` or add the environment's `Scripts`/`bin` directory to `PATH`.

**Exit code `3`**

YouTube rate-limited a caption request. Stop the run, wait, and retry later.
Lower `-w`, add a cookie file or proxy, and avoid immediately retrying the same
video. `download --json` reports `retry_after` when the server sent one.

**Exit code `4`**

No requested transcript exists. Run `salin inspect URL` to see the available
codes. Remember that `-l en` can resolve to regional variants such as `en-US`,
but a video with only `de` will not produce English text.

**`no subtitle files found`**

`clean` selected no files. Check the extensions (`.vtt`, `.srt`, `.json3`,
`.srv1`, `.srv2`, `.srv3`, `.ttml`) and add `--recursive` for nested
directories.

**`invalid choice`**

The format name is wrong. Use one of `text`, `json`, `jsonl`, `srt`, `vtt` for
`fetch --format`, or one of the seven subtitle formats for `download -f`.

**Repeated or overlapping text**

That is expected for auto-generated captions fetched with `fetch`. Download the
file and run `salin clean` to merge overlapping cues.

**Non-ASCII text looks wrong**

All files and JSON are written as UTF-8. If text is garbled, the terminal or
downstream consumer is using a different encoding.

## Limits

The CLI is intentionally a thin wrapper around the library, so it does not add:

- playlist or channel expansion (one URL per video);
- resume, skip-existing, or retry flags for downloads (existing files are
  overwritten; re-run the command to retry);
- a progress bar (paths are printed as videos complete);
- built-in pacing between videos (use a shell loop or the library's
  `download_many` consumer);
- parallel fetches (`fetch` processes URLs sequentially; only `download` has
  `-w`);
- transcript cleaning during `fetch` (`fetch` returns raw caption text).

For those workflows, use the [Python API](README.md#quick-start) directly.

## See also

- [README: quick start and API](README.md#quick-start)
- [README: cleaning auto-captions](README.md#cleaning-auto-captions)
- [README: worker benchmark](README.md#how-many-workers-to-use)
- [README: rate limits](README.md#rate-limits)
