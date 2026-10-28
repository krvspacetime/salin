<p align="center">
  <img src="https://raw.githubusercontent.com/krvspacetime/salin/main/assets/logo.svg" width="96" height="96" alt="Salin logo">
</p>

<h1 align="center">Salin</h1>

<p align="center">
  Inspect, resolve, download, and clean YouTube subtitle tracks from Python.
</p>

<p align="center">
  <a href="https://github.com/krvspacetime/salin/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python 3.12 | 3.13" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg">
  <a href="https://github.com/krvspacetime/salin/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/krvspacetime/salin/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Lint: ruff" src="https://img.shields.io/badge/lint-ruff-261230.svg">
  <img alt="Types: mypy-style, checked with ty" src="https://img.shields.io/badge/types-ty-ffd43b.svg">
  <a href="https://pypi.org/project/salin/"><img alt="PyPI" src="https://img.shields.io/pypi/v/salin.svg?style=flat"></a>
  <a href="https://github.com/sponsors/krvspacetime"><img alt="Sponsor" src="https://img.shields.io/badge/sponsor-%E2%9D%A4-ff69b4.svg"></a>
</p>

---

Salin is a typed Python library for working with YouTube subtitle tracks. It
reports which manual and automatic tracks a video offers, resolves requested
languages against configurable match and source policies, downloads captions in
seven formats, and can return transcripts in memory as snippets. Auto-generated
captions can also be cleaned into deduplicated prose.

- Manual and automatic tracks, including regional variants such as `en-US`
  and `pt-BR`
- `vtt`, `srt`, `json3`, `srv1`, `srv2`, `srv3`, and `ttml`
- Files on disk with `download()`, snippets in memory with `fetch()`
- Cleaned transcripts with `clean_transcript()`
- Bulk downloads through a thread pool
- Rate limits reported as `RateLimitedError` and `DownloadStatus.RATE_LIMITED`
- Browser cookies, `cookies.txt`, and HTTP/SOCKS proxies
- Fully typed (`py.typed`), Python 3.12+

## Install

```bash
pip install salin
```

Or with uv:

```bash
uv add salin
```

Requires Python 3.12 or newer.

## Quick start

```python
from salin import Salin

client = Salin(languages="en")

result = client.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
for sub in result.ok_subs:
    print(sub.sub_path)          # salin_downloads/dQw4w9WgXcQ.en.vtt

transcript = client.fetch("dQw4w9WgXcQ")
for snippet in transcript:
    print(snippet.start, snippet.text)
```

Subtitles are written to `./salin_downloads` unless you pass `output_dir` to
the client or to the call.

## Inspecting available tracks

`inspect()` reports the manual and automatic tracks a video exposes, along with
the formats each track is available in. Nothing is downloaded.

```python
url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
availability = Salin().inspect(url)

availability.video_id
availability.title
availability.manual          # frozenset({'de-DE', 'en', 'es-419', 'ja', 'pt-BR'})
availability.auto            # frozenset({'en', 'en-orig'})
availability.manual_formats  # {'en': frozenset({'json3', 'srt', 'srv1', ...}), ...}
availability.auto_formats
```

## Resolving languages

`resolve()` maps each requested language to a track according to
`language_match`, `source_policy`, and optional per-language aliases.

```python
resolved = Salin().resolve(
    url,
    languages={"en": ["en-US", "en-GB"], "de": ["de-DE", "de-AT"]},
    language_match="exact",
    source_policy="manual_only",
)

for item in resolved:
    print(item.requested, item.resolved, item.source)
```

The defaults are `language_match="regional"` and
`source_policy="manual_then_auto"`. Available values:

```python
LanguageMatch.EXACT        # "en" resolves only to "en"
LanguageMatch.REGIONAL     # "en" may resolve to en-US, en-orig, etc.

SubtitleSourcePolicy.MANUAL_ONLY
SubtitleSourcePolicy.AUTO_ONLY
SubtitleSourcePolicy.MANUAL_THEN_AUTO
SubtitleSourcePolicy.AUTO_THEN_MANUAL
```

The two settings constrain each other. For example, `language_match="exact"`
with `source_policy="auto_only"` will not fall back to a manual `en` track even
when one exists. A request that cannot be satisfied resolves to `None`.

## Downloading subtitles

```python
client = Salin(languages=["en", "de"], output_dir="subs")
result = client.download(url)

for sub in result.subtitles:
    print(sub.requested, sub.resolved, sub.source, sub.status, sub.sub_path)
```

Each requested language becomes its own file, named
`<video_id>.<language>.<format>`. VTT is the default; pick another format per
call:

```python
client.download(url, subtitle_format="srt")
```

Per-subtitle failures are part of the result rather than exceptions. `status` is
`ok`, `missing`, `unavailable`, `rate_limited`, or `error`, with details in
`.error`; `result.ok_subs` returns only the files that were written. Pass
`strict=True` to raise instead.

## Fetching transcripts in memory

`fetch()` returns snippets directly and writes nothing to disk. It accepts a
full URL or a bare video ID and honors the same language, source, and proxy
options as `download()`.

```python
transcript = Salin(languages="en").fetch("dQw4w9WgXcQ")

len(transcript)                 # number of snippets
transcript.video_id             # 'dQw4w9WgXcQ'
transcript.language             # 'English' (YouTube's name for the track)
transcript.language_code        # 'en'
transcript.is_generated         # False for manual, True for auto
transcript.text                 # every snippet joined with a space
transcript.to_raw_data()        # [{'text': ..., 'start': ..., 'duration': ...}]

for snippet in transcript:      # .text / .start / .duration in seconds
    print(snippet.start, snippet.text)
```

`fetch()` reads the `json3` track when one exists, falling back to `srv3`,
`srv1`, `srv2`, `ttml`, or `vtt`.

### Migrating from `youtube-transcript-api`

```diff
- from youtube_transcript_api import YouTubeTranscriptApi
- transcript = YouTubeTranscriptApi().fetch(video_id, languages=("en",))
+ from salin import Salin
+ transcript = Salin(languages="en").fetch(video_id)
```

The returned objects mirror the ones from `youtube-transcript-api`, with a few
differences:

- The language list belongs on the client or in a `languages=` override, not in
  a positional argument.
- Snippets are normalized: inline markup, speaker chevrons (`>>`), and stage
  directions such as `[Music]` are stripped, and whitespace is collapsed.
- `preserve_formatting=True` is not supported and raises `SalinValueError`.
- Failures raise Salin errors: `TranscriptUnavailableError` when no requested
  language resolves, and `SubtitleDownloadError` when the caption request
  itself fails. A `429` raises `RateLimitedError` with `.retry_after` set when
  the server sent a `Retry-After` header.

## Cleaning auto-captions

Downloaded files are exactly what YouTube serves: auto-generated tracks come in
short overlapping windows, with word-timing tags and display markup in between.
`clean_transcript()` merges the overlaps and strips the markup.

```text
multiple hours to capture the same level
multiple hours to capture the same level
of<00:48:19.119><c> mistake</c><00:48:19.520><c> because</c> ...
of mistake because it requires like
```

After cleaning:

```text
multiple hours to capture the same level of mistake because it requires like
```

```python
from salin import Salin, clean_transcript

result = Salin(languages="en", subtitle_format="vtt").download(url)
paths = clean_transcript(result, output_dir="transcripts")
```

To clean a file without writing anything:

```python
from salin import clean_cues

subtitle = result.ok_subs[0]
text = clean_cues(subtitle.sub_path, subtitle.format)
```

`max_workers` cleans in parallel (default `1`). Without `output_dir`, each
transcript is written next to its source. Every subtitle format is parsed:
`vtt`, `srt`, `json3`, `srv1`, `srv2`, `srv3`, and `ttml`.

**VTT is approximate.** It is the only rolling format, and YouTube sometimes
repeats a word inside a single cue where the overlap merge cannot see it. On a
72-minute auto-captioned podcast the cleaned VTT was 0.3% longer (41 words) than
the same video's other six formats. Manual tracks are usually not rolling;
prefer `srt`, `srv1`, `srv3`, `json3`, or `ttml` when you need exact text.

## Bulk downloads

`download_many()` is an `Iterator[SubtitleResult]` backed by a thread pool.
Results are yielded as they finish, so order is preserved only with
`max_workers=1`.

```python
client = Salin(languages="en")

for result in client.download_many(urls, max_workers=3):
    if not result.processable:
        continue
    for subtitle in result.ok_subs:
        print(subtitle.sub_path)
```

`result.processable` is a copy of the result containing only the successful
subtitles, or `None` when nothing succeeded.

### How many workers to use

Measured on 8 videos, one language each, median of 3 rounds:

| `max_workers` | wall time | speedup |
|---:|---:|---:|
| 1 | 40.9s | 1.0x |
| 2 | 23.5s | 1.7x |
| 3 | 21.3s | 1.9x |
| 4 | 21.8s | 1.9x |
| 6 | 20.2s | 2.0x |

Two or three workers is the practical ceiling. Each download spends about 4s on
metadata extraction and only ~0.3s fetching subtitle bytes, and YouTube throttles
concurrent extraction requests. Past three workers the gain is a few percent at
best, and the tail gets worse: one run with four workers took 38.4s, slower than
running sequentially. If bulk jobs stall, lower the worker count rather than
raising it.

## Rate limits

Salin adds no delay by default (`sleep_interval_subtitles=0`). Raise it when
request volume, not latency, is the concern:

```python
client = Salin(languages=["en", "de", "ja"], sleep_interval_subtitles=2)
```

Each extra language then costs `(languages - 1) x interval` seconds per video.
`sleep_interval_requests` is forwarded to yt-dlp and only applies when yt-dlp
performs the download itself.

YouTube rate-limits its caption endpoint independently of page extraction. When
that happens Salin records a distinct status instead of retrying blindly:

```python
result = client.download(url)

if result.is_rate_limited:
    print(result.retry_after)          # largest Retry-After seen, or None
    for sub in result.rate_limited_subs:
        print(sub.requested, sub.error)
```

- A `429` is never retried and never delegated to yt-dlp, which would retry the
  same limited endpoint with long, silent backoff.
- `Retry-After` (delta-seconds or an HTTP-date) is parsed into
  `SubtitleFile.retry_after`; `SubtitleResult.retry_after` reports the largest
  value across the requested subtitles.
- Transient failures (5xx, connection errors, timeouts) are retried twice with
  jittered backoff. An expired signed URL (`403`) is refreshed once by
  re-extracting the video.

Use `strict=True` to raise instead of returning a partial result:

```python
from salin import RateLimitedError

try:
    client.download(url, strict=True)
except RateLimitedError as exc:
    wait = exc.retry_after or 60
```

For batches, `max_consecutive_rate_limits` stops the generator once that many
rate-limited results arrive in a row. The counter resets on any other result;
with `max_workers > 1`, "consecutive" is approximate because results arrive in
completion order.

```python
for result in client.download_many(urls, max_consecutive_rate_limits=3):
    ...
```

## Cookies and proxies

Some videos only expose subtitles to signed-in, region-locked, or differently
routed clients. Configure this on the client or per call:

```python
client = Salin(
    languages="en",
    cookies="firefox:myprofile",        # read from a browser
    # cookiefile="~/cookies.txt",       # or a Netscape cookies.txt you control
    # proxy="socks5://127.0.0.1:1080",  # or route through a proxy
)

result = client.download(url, cookies="chrome", proxy="http://127.0.0.1:8080")
```

`cookies` uses yt-dlp's syntax: `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`, for
example `"chrome"`, `"firefox"`, `"firefox+gnomekeyring"`, or
`"chromium::Container 1"`. `cookiefile` must be an existing Netscape-format
`cookies.txt`. `proxy` accepts `http`, `https`, `socks4`, `socks4a`, `socks5`,
and `socks5h` URLs. Invalid values raise `SalinValueError` before any request is
made.

These settings apply to metadata extraction, the direct caption fetch, the
yt-dlp fallback, `fetch()`, and the re-extraction after an expired signed URL.
`inspect()` and `resolve()` accept them too.

`fetch()` reads caption bytes with `urllib`, so it only supports `http://`
proxies. With `https://`, `socks4`, or `socks5`, it raises `SalinValueError` and
points at `download()`, which delegates the fetch to yt-dlp and supports every
scheme.

> **Security note:** `cookies` reads the browser's cookie store and sends your
> logged-in session to the remote site with every request. Only use it with
> sources you trust, and prefer a `cookies.txt` you control on shared machines.

## Performance

Metadata extraction dominates: roughly 4s per video, against ~0.3s for the
caption bytes. `inspect()`, `resolve()`, `fetch()`, and `download()` each extract
once, so calling three of them on the same video repeats that cost three times.
`download()` already resolves every requested language and reports the results,
so most flows need a single call.

To share one extraction across stages, pass `info=`:

```python
from salin import extract_info

info = extract_info(url)
availability = client.inspect(url, info=info)
resolved = client.resolve(url, languages=["en", "de"], info=info)
transcript = client.fetch(url, languages="en", info=info)
result = client.download(url, languages=["en", "de"], info=info)
```

That pipeline takes about 4.6s instead of 12s. `info` must come from
`extract_info()`; hand-built dicts are rejected and playlists are not supported.

`extract_info()` keeps one yt-dlp client per thread and request configuration,
so back-to-back calls skip about 0.3s of setup; a repeated extraction drops from
~3.0s to ~1.2–1.6s. Salin also caps yt-dlp's default retry counts and socket
timeout, so a stuck request fails fast rather than stalling a batch.

## How it compares

If you only need in-memory snippets from YouTube, `youtube-transcript-api` is
smaller and faster per video. Salin covers more of the surrounding work: files
on disk, format conversion, cleaning, bulk runs, and behavior you can reason
about when YouTube starts refusing requests.

| | youtube-transcript-api | Salin |
|---|---|---|
| Snippets in memory | yes | yes (`fetch()`) |
| Subtitle files on disk | no | yes (7 formats) |
| Cleaning / dedup | no | yes |
| Language resolution | basic | manual/auto policies, regional variants |
| Bulk downloads | no | `download_many()` with workers |
| Browser cookies | no | yes |
| Proxy / `cookiefile` | proxy only | `cookies`, `cookiefile`, `proxy` |
| Rate-limit signal | `IpBlocked` | `RateLimitedError` + status + `Retry-After` |
| Survives a watch-page block | no | yes (inspection and resolution keep working) |
| Python | 3.9+ | 3.12+ |

## Benchmarks

Measured on one residential IP (Windows) with `yt-dlp 2026.07.04`,
`youtube-transcript-api 1.2.4`, and Salin 0.1.0, English only, sequential, no
artificial delay. The machine was in normal use, so sub-second differences are
noise; block onset and success/failure are reliable.

### Random sample: 1,000 videos

The sample is 1,000 videos drawn uniformly from a database of 9,776. Only 50 of
them were marked as having captions, so the sample is not biased toward videos
known to have subtitle tracks. Every video was attempted:

| outcome | videos | share |
|---|---:|---:|
| English transcript returned | 898 | 89.8% |
| no captions at all | 96 | 9.6% |
| English only as machine translation | 5 | 0.5% |
| video unavailable | 1 | 0.1% |

- **Zero blocks** over 88.1 minutes, an average of 11.4 videos/min.
- Latency on the 898 successes: mean 5.58s, p50 5.06s, p95 9.66s.
- Throughput rose through the run: 9.8 → 12.9 videos/min per 200-video segment.
- The other 101 videos were re-extracted and classified. None had a native
  English track that Salin failed to fetch: 96 have no captions at all, and 5 are
  non-English videos whose only `en` track is a machine translation, which Salin
  skips by default rather than silently returning translated text.

An earlier 480-video run over videos already marked as captioned averaged
15.0 videos/min with zero blocks (p50 3.25s). The higher rate reflects a
different, easier sample rather than a code change.

> `captions_available` is not a reliable filter: 898 of these 1,000 videos had
> captions, but only 50 were marked. Treat an unset flag as unknown.

### Against `youtube-transcript-api`

On the 55 videos both libraries handled, content matched exactly: median raw
characters 7,032 vs 7,032, median snippets 116 vs 116, median ratio 1.000, and
no video off by more than one character. On those 55 videos Salin averaged
3.86s against 1.22s, because it pays for a full yt-dlp metadata extraction.

| | youtube-transcript-api | Salin |
|---|---:|---:|
| Sequential throughput | ~31 videos/min until blocked | 11–15 videos/min |
| Watch-page API block | after ~100s of requests | not observed in 88 minutes |
| Behavior after a block | every request fails | `inspect()` and `resolve()` still work; caption fetches return 429 |

`youtube-transcript-api` drives the watch page directly and blocks after roughly
100 seconds of sequential requests (video #56 and #89 in two runs). Once
blocked, it stayed blocked for the rest of the day.

Caption bytes come from the same `api/timedtext` endpoint for both libraries, so
Salin shares that limit and can be rate-limited too. What differs is the
response: Salin returns `DownloadStatus.RATE_LIMITED` or raises
`RateLimitedError` with `Retry-After`, and keeps inspecting and resolving while
the endpoint is closed. At ~11 videos/min the limit did not trip; Salin has not
been shown to survive `youtube-transcript-api`-level throughput.

## Other sites

Extraction goes through yt-dlp, so YouTube is not a hard limit, but there is no
dedicated support beyond that. Another site works only if yt-dlp exposes its
subtitle tracks in one of the supported formats.

Of the sites tried, only Dailymotion worked end to end (it offered `srt`).
Vimeo returned an OAuth 401, TED raised an extractor error, and archive.org
exposed no captions. Call `inspect()` first to see what a site actually offers.

## Development

```bash
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run ty check
uv run pytest
```

CI runs the same commands on Python 3.12 and 3.13.

## License

MIT - see [LICENSE](https://github.com/krvspacetime/salin/blob/main/LICENSE).
