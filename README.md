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
  <a href="https://pypi.org/project/salin/"><img alt="PyPI" src="https://img.shields.io/pypi/v/salin.svg"></a>
  <a href="https://github.com/sponsors/krvspacetime"><img alt="Sponsor" src="https://img.shields.io/badge/sponsor-%E2%9D%A4-ff69b4.svg"></a>
</p>

---

Salin is a typed Python library for working with YouTube subtitle tracks. It
inspects which tracks and formats a video has, resolves requested languages
against language-match and source policies, downloads the captions (to disk or
straight into memory as snippets), and cleans rolling auto-caption noise into
prose you can read, index, or feed to a model.

It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) for extraction. YouTube is the
primary, tested target; other sites are best-effort and depend on what yt-dlp can
expose (see [Other sites](#other-sites)).

## Why this exists

`youtube-transcript-api` is a great default — small, in-memory, easy to install.
It is also easy to break: it talks to YouTube's private player API, so when
YouTube blocks your IP the library stops working entirely, and a burst of
requests can get you a shared `429` with no clear signal.

Salin uses yt-dlp's extraction, which is more resilient and keeps
**inspecting and resolving** subtitle availability even when the caption
endpoint is throttling. It also treats rate limits as a first-class result
rather than a silent retry: you get `RateLimitedError` / `DownloadStatus.RATE_LIMITED`
with the parsed `Retry-After`, and a bulk run can stop cleanly instead of
hammering an endpoint that is already refusing it. Honest about the one limit it
shares with everyone: caption *bytes* come from the same `timedtext` endpoint, so
Salin can be rate-limited too — it just tells you instead of hiding it.

## How it compares

| | youtube-transcript-api | Salin |
|---|---|---|
| Snippets in memory | yes | yes (`fetch()`) |
| Subtitle files on disk | no | yes (7 formats) |
| Cleaning / dedup | no | yes |
| Language resolution policies | limited | manual/auto, regional variants |
| Bulk API | no | `download_many` with workers |
| Browser cookies | no | yes |
| Proxy / `cookiefile` | proxy only | `cookies`, `cookiefile`, `proxy` |
| Explicit rate-limit error | `IpBlocked` | `RateLimitedError` + status |
| Survives a watch-page IP block | no | yes (inspection still works) |
| Typed package | yes | yes (`py.typed`) |
| License | MIT | MIT |
| Python | 3.9+ | 3.12+ |

## Install

```bash
pip install salin
```

Or with uv:

```bash
uv add salin
```

Requires Python 3.12+.

## Quick start

```python
from salin import Salin

client = Salin(languages="en")
result = client.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
# Subtitles are saved to ./salin_downloads unless you set output_dir on the
# client or on download()/download_many().
```

Prefer snippets in memory? Use `fetch()`:

```python
transcript = Salin(languages="en").fetch("dQw4w9WgXcQ")
for snippet in transcript:
    print(snippet.start, snippet.text)
```

## Downloading subtitles

Pick a format:

```python
client = Salin()
result = client.download(
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    subtitle_format="vtt",
)
```

Download several languages in one call:

```python
client = Salin(languages=["en", "de"])
result = client.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
print(result)
```

```text
SubtitleResult(
    url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    video_id='dQw4w9WgXcQ',
    title='Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)',
    subtitles=(
        SubtitleFile(
            requested='en',
            resolved='en',
            source=<SubtitleSource.MANUAL: 'manual'>,
            status=<DownloadStatus.OK: 'ok'>,
            sub_path=WindowsPath('salin_downloads/dQw4w9WgXcQ.en.vtt'),
            format=<SubtitleFormat.VTT: 'vtt'>,
            error=None),
        SubtitleFile(
            requested='de',
            resolved='de-DE',
            source=<SubtitleSource.MANUAL: 'manual'>,
            status=<DownloadStatus.OK: 'ok'>,
            sub_path=WindowsPath('salin_downloads/dQw4w9WgXcQ.de-DE.vtt'),
            format=<SubtitleFormat.VTT: 'vtt'>,
            error=None)))
```

### Other sites

Extraction is delegated to yt-dlp, so YouTube is not a hard limit — but support
depends on the site exposing subtitle tracks in a format you ask for, and on
yt-dlp having the right networking dependency (some extractors need
impersonation, e.g. `curl_cffi` for Dailymotion).

Verified end to end: **Dailymotion**, which offered only `srt` in our sample:

```python
client = Salin(languages="en", subtitle_format="srt")
result = client.download("https://www.dailymotion.com/video/x7tgad0")
```

Not verified here: Vimeo (OAuth 401), TED (extractor error) and archive.org (no
captions exposed). Treat other sites as best-effort and call `inspect()` first to
see which formats are actually available.

## Fetch transcripts in memory

`fetch()` is the `youtube-transcript-api`-shaped path: it returns snippets
directly, writes no file, and does not download the video.

```python
from salin import Salin

transcript = Salin(languages="en").fetch("dQw4w9WgXcQ")
len(transcript)                      # number of snippets
transcript.video_id                  # 'dQw4w9WgXcQ'
transcript.language                  # 'English' (YouTube's name for the track)
transcript.language_code             # 'en'
transcript.is_generated              # False for a manual track, True for auto

for snippet in transcript:           # snippet.text / .start / .duration (seconds)
    print(snippet.start, snippet.text)

transcript.to_raw_data()             # [{'text': ..., 'start': ..., 'duration': ...}]
transcript.text                      # every snippet joined with a space
```

`fetch()` accepts a full URL or a bare video ID, and honors the same
`language_match`, `source_policy`, and `info=` options as `download()`. It
fetches the `json3` track when one exists (falling back to `srv3`, `srv1`,
`srv2`, `ttml`, or `vtt`), in memory.

### Migrating from `youtube-transcript-api`

```diff
- from youtube_transcript_api import YouTubeTranscriptApi
- transcript = YouTubeTranscriptApi().fetch(video_id, languages=("en",))
+ from salin import Salin
+ transcript = Salin(languages="en").fetch(video_id)
```

The returned objects mirror yta's:

```python
from salin import FetchedTranscript, TranscriptSnippet
```

Differences to know about:

- `fetch()` takes the language list in the `Salin(...)` constructor (or a
  `languages=` override), not as a positional argument.
- Snippets are **normalized**: inline markup, speaker chevrons (`>>`), and
  stage directions such as `[Music]` are stripped, and whitespace is
  collapsed. `youtube-transcript-api` only strips HTML tags, so text can
  differ slightly for captions that contain those markers.
- `preserve_formatting=True` is not supported and raises `SalinValueError`.
- Failures raise Salin errors: `TranscriptUnavailableError` when no
  requested language resolves, and `SubtitleDownloadError` when the caption
  request itself fails.
- A `429` raises `RateLimitedError` (a `SubtitleDownloadError` subclass) with
  `.retry_after` set from the server's `Retry-After` header when present.

## Inspecting available subtitles

`inspect()` reports the available manual and automatic tracks plus the formats
each one offers.

```python
client = Salin()
availability = client.inspect(url)
print(availability)
```

```text
SubtitleAvailability(
    url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    video_id='dQw4w9WgXcQ',
    title='Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)',
    manual=frozenset({'pt-BR', 'es-419', 'de-DE', 'en', 'ja'}),
    auto=frozenset({'en', 'en-orig'}),
    manual_formats={'en': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), ...},
    auto_formats={'en-orig': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), ...})
```

## Resolving languages

`resolve()` returns the `ResolvedSubtitle` for each request according to the
`language_match`, `source_policy`, and per-language alias list.

```python
client = Salin()
result = client.resolve(
    url,
    language_match="exact",          # LanguageMatch.EXACT
    source_policy="manual_only",     # SubtitleSourcePolicy.MANUAL_ONLY
    languages={"en": ["en-US", "en-GB"], "de": ["de-DE", "de-AT"]},
)
print(result)
# (ResolvedSubtitle(requested='en', resolved='en', source=None),
#  ResolvedSubtitle(requested='de', resolved=None, source=None))
```

If `resolved` is `None`, the resolver could not satisfy the request under the
given availability, language match, and source policy.

### Language match and source policy

Both settings constrain each other. For example, if `language_match="exact"`
but `source_policy="auto_only"`, the client will not use a requested `en`
track even when a manual one is available.

```python
LanguageMatch.EXACT        # "en" only resolves to "en"
LanguageMatch.REGIONAL     # "en" can resolve to en-US, en-orig, etc.

SubtitleSourcePolicy.MANUAL_ONLY
SubtitleSourcePolicy.AUTO_ONLY
SubtitleSourcePolicy.MANUAL_THEN_AUTO
SubtitleSourcePolicy.AUTO_THEN_MANUAL
```

## One metadata fetch per call

`inspect()`, `resolve()`, `fetch()`, and `download()` each fetch the video's
metadata once. That fetch is ~4s and ~98% of a download's wall time (the bytes
are ~0.3s), so calling three of them on one video costs ~12s — the same metadata
three times.

`download()` already resolves and reports every requested language, so most
flows need just one call:

```python
result = client.download(url)
for sub in result.subtitles:
    print(sub.requested, sub.resolved, sub.status)
```

When you need the intermediate stages, extract once and pass `info=`:

```python
info = extract_info(url)                                # one request per video
availability = client.inspect(url, info=info)
resolved = client.resolve(url, languages=["en", "de"], info=info)
transcript = client.fetch(url, languages="en", info=info)
result = client.download(url, languages=["en", "de"], info=info)
```

That pipeline is ~4.6s versus ~12s for three independent calls. `info` must come
from `extract_info()`: hand-built or trimmed dicts are rejected, and playlists
are not supported.

## Cleaning transcripts

`download()` writes the subtitle file exactly as YouTube serves it — a poor
thing to read, index, or feed to a model. `clean_transcript()` turns it into
prose.

Auto-captions are written in short overlapping windows, so the same phrase
appears on screen several times, with inline word-timing tags in between:

```text
multiple hours to capture the same level
multiple hours to capture the same level
of<00:48:19.119><c> mistake</c><00:48:19.520><c> because</c> ...
of mistake because it requires like
```

They also carry display markup and stage directions (`[Music]`, `(laughter)`,
`>>`, `♪`, `<br />`). Cleaning strips that markup, merges the overlapping
windows, and returns one paragraph:

```text
multiple hours to capture the same level of mistake because it requires like
```

Write the cleaned text next to (or into) a directory:

```python
from salin import Salin, clean_transcript

result = Salin(languages="en", subtitle_format="vtt").download(url)
paths = clean_transcript(result, output_dir="transcripts")
```

Or get it without touching the filesystem:

```python
from salin import clean_cues

subtitle = result.ok_subs[0]
text = clean_cues(subtitle.sub_path, subtitle.format)
```

`max_workers` cleans in parallel (default `1`); with `output_dir` omitted each
transcript is written next to its source. Every `SubtitleFormat` is parsed:
`vtt`, `srt`, `json3`, `srv1`, `srv2`, `srv3`, `ttml`.

**VTT is approximate.** It is the only rolling format, and YouTube sometimes
repeats a word *inside* one cue where the overlap merge cannot see it. On a
72-minute auto-captioned podcast the cleaned `vtt` came out 0.3% longer (41
words) than the same video's other six formats. Manual tracks are usually not
rolling; choose `srt`, `srv1`, `srv3`, `json3`, or `ttml` when you need exact
text.

## Bulk downloads

`download_many()` returns an `Iterator[SubtitleResult]`, so it is the right tool
for batches. It is implemented with a `ThreadPoolExecutor`, and `max_workers`
can be set (default `1`).

> **Note:** `download_many` is both faster and more memory efficient than
> calling `download` in a loop. Results are yielded as they finish, so input
> order is not preserved unless `max_workers=1`.

```python
client = Salin()

for result in client.download_many(urls, languages="en", max_workers=3):
    if not result.processable:
        continue
    for subtitle in result.ok_subs:
        print(subtitle.sub_path)
```

### How many workers to actually use

Measured on 8 videos (one language each, median of 3 rounds):

| `max_workers` | wall time | speedup |
|---:|---:|---:|
| 1 | 40.9s | 1.0x |
| 2 | 23.5s | 1.7x |
| 3 | 21.3s | 1.9x |
| 4 | 21.8s | 1.9x |
| 6 | 20.2s | 2.0x |

**Treat 2–3 as the practical ceiling.** Every download spends ~4s fetching
metadata and only ~0.3s fetching the subtitle, so the bottleneck is yt-dlp's
per-video extraction, and YouTube throttles those concurrent requests. Past 3
workers the gain is a few percent at best, and the tail is worse than the
mean: one run at `max_workers=4` took 38.4s — slower than sequential — while
another took 18.8s. If you see bulk jobs stalling, drop to 2–3 workers rather
than raising it.

## Benchmarks

One residential IP, Windows, `yt-dlp 2026.07.04`, `youtube-transcript-api 1.2.4`,
`Salin 0.1.0`, 2026-10-27/28, `en` only, sequential, no artificial delay.
Two samples from the same Postgres table: 480 videos where `captions_available =
true`, and 1,000 videos sampled uniformly from all 9,776 rows. Both were
shuffled with a fixed seed. Times are local and the machine was in normal use,
so sub-second differences are noise; block onset and success/failure are
reliable.

### How fast each library gets blocked

| run | attempted | succeeded | first block | wall | throughput | p50 latency |
|---|---:|---:|---|---:|---:|---:|
| `youtube-transcript-api` | 60 | 55 | #56, ~99s | 105s | 34.4/min | 1.22s |
| Salin | 480 | 479 | none | 31.9 min | 15.0/min | 3.25s |

`youtube-transcript-api` made 55 consecutive requests at ~1.2s each, then hit
`IpBlocked` and failed every request after that. An earlier run blocked at #89
after ~103s, so the stable number is the wall time, not the video count:
`youtube-transcript-api` is good for roughly **100 seconds** of sequential
requests.

Salin then ran 479 of 480 in one continuous 31.9-minute session with
**zero blocks**; the one failure was a genuinely unavailable video, so its
success rate on usable videos is 100%. A further 1,000-video random sample ran
88 more minutes on the same IP, also with zero blocks (see below).

### The limit both libraries share

Caption bytes come from the same `youtube.com/api/timedtext` endpoint whichever
library asks. Running `youtube-transcript-api` first poisoned the next
Salin run: yt-dlp still extracted `id`, `title`, and the full caption
track list, but every caption fetch returned `HTTP 429`. So the useful claim is
narrower than "yt-dlp doesn't get blocked":

- Salin keeps **inspecting and resolving** while `youtube-transcript-api`
  is blocked.
- Caption bytes are rate-limited separately, and a burst from either library
  spends the same budget.

At ~15 videos/min the limit did not trip for half an hour. We have not shown it
survives `youtube-transcript-api`-level throughput (~34/min); it probably would
not.

### How long a block lasts

- The `youtube-transcript-api` block was still active 35+ minutes after it
  started, and the shared `timedtext` limit stayed closed long enough to ruin
  the next run.
- A second burst kept the endpoint closed for well over an hour: a probe every
  5 minutes still got `429` at the 60-minute mark. The ~45-minute recovery seen
  once was the short case, not the norm.
- In practice a burst like this has kept the IP limited for **1–2 days** on this
  connection — repeated observation, not one controlled measurement.
- Metadata is never the thing that gets blocked. yt-dlp extraction kept working
  throughout, and switching to a fresh IP cleared the limit immediately.

### Content parity

| metric | youtube-transcript-api | Salin |
|---|---:|---:|
| raw characters (median) | 7032 | 7032 |
| snippets (median) | 116 | 116 |
| latency (mean) | 1.22s | 3.86s |

Measured on the 55 videos both libraries handled; the median ratio was exactly
1.000 and no video diverged by more than one character. Salin is ~3x
slower per video because it pays a full yt-dlp extraction — the price of
surviving the watch-page block.

### Success rate on a random sample

The 480-video runs used a hand-marked subset, so they cannot say how often a
video actually has captions. A separate run sampled **1,000 of the 9,776**
videos uniformly (only 50 of them marked captioned) and processed every one:

| outcome | videos | share |
|---|---:|---:|
| English transcript returned | 898 | 89.8% |
| no captions at all | 96 | 9.6% |
| English only as a machine translation | 5 | 0.5% |
| video unavailable | 1 | 0.1% |

**Zero blocks over 88 minutes.** Every one of the 101 misses was checked: none
had a native English track that Salin failed to fetch. 96 have no captions
at all; the 5 are non-English videos whose only `en` track is a machine
translation, which Salin skips by default rather than silently returning
translated text.

That is also a warning about `captions_available`-style filters: 898 of the
1,000 videos had captions, but only 50 were marked. Treat an unset flag as
unknown, not as "no captions".

### Throughput

Throughput is not stable enough to quote one number:

- The 480-video run above averaged 15.0/min, dipped mid-run (10.6/min for
  #101–200), then recovered to ~18/min for the last 280.
- The 1,000-video random sample averaged 11.4/min and **sped up** over time
  (9.8 → 12.9/min).
- An earlier 480-video run averaged 11.0/min and stayed near 10/min after the
  first hundred.

Expect roughly **10–18 videos/min** single-threaded, with no hard block in
either 480-video session. The faster run is also the first to reuse a `YoutubeDL`
across videos (the pooled client), which likely explains much of the spread —
though the two runs used different IPs, so it is not a controlled comparison.

### When you will still get blocked

- A burst of dozens of videos in a minute can close the shared `timedtext`
  limit for hours to days, with either library.
- Page-level blocks (yta's failure) do not stop `inspect()` or `resolve()`; the
  caption endpoint still does.
- Pace bulk work at ~10–15 videos/min, use 2–3 workers, and set
  `max_consecutive_rate_limits` so a run stops instead of hammering a closed
  endpoint.

## Throttling and rate limits

Salin adds no artificial delay by default: `sleep_interval_subtitles`
defaults to `0`. Raise it when request volume, not latency, is the bottleneck:

```python
client = Salin(languages=["en", "de", "ja", "pt-BR"], sleep_interval_subtitles=2)
```

Each extra language then costs `(languages - 1) x interval` seconds per video.
`sleep_interval_requests` is forwarded to yt-dlp and only applies when yt-dlp
performs the download itself.

### When YouTube rate-limits you

YouTube enforces a shared limit on the `timedtext` caption endpoint that is
independent of yt-dlp's page requests. When it trips, the request comes back
`HTTP 429`, and Salin records it as a distinct status instead of a generic
error:

```python
result = client.download(url)

if result.is_rate_limited:
    print(result.retry_after)              # seconds from Retry-After, or None
    for sub in result.rate_limited_subs:
        print(sub.requested, sub.error)
```

- A `429` is **never retried** and never handed to yt-dlp, because yt-dlp
  would retry the same limited endpoint with long, silent backoff.
- `Retry-After` (delta-seconds or an HTTP-date) is parsed into
  `SubtitleFile.retry_after`, and `SubtitleResult.retry_after` reports the
  largest value seen across the requested subtitles.
- Transient failures (5xx, connection errors, timeouts) are retried twice with
  short jittered backoff. An expired signed URL (`403`) is refreshed once by
  re-extracting the video before giving up.

Pass `strict=True` to raise instead of returning a partial result:

```python
from salin import RateLimitedError

try:
    client.download(url, strict=True)
except RateLimitedError as exc:
    wait = exc.retry_after or 60
```

For batches, cap how many rate-limited videos in a row you tolerate. The
generator ends when the cap trips, so you can stop instead of hammering an
endpoint YouTube has already throttled:

```python
results = client.download_many(urls, max_consecutive_rate_limits=3)
for result in results:
    ...
# Stopped early; everything yielded so far is inspectable.
```

The counter resets on any non-rate-limited result. With `max_workers > 1`,
"consecutive" is approximate because results arrive in completion order.

## Cookies and proxies

Some videos only expose subtitles to signed-in, region-locked, or differently
routed clients. Pass the settings at the client level or per call:

```python
client = Salin(
    languages="en",
    cookies="firefox:myprofile",        # read from a browser
    # cookiefile="~/cookies.txt",       # or a Netscape cookies.txt you control
    # proxy="socks5://127.0.0.1:1080",  # or route through a proxy
)

# per call, overriding the client
result = client.download(url, cookies="chrome", proxy="http://127.0.0.1:8080")
```

`cookies` uses yt-dlp's syntax: `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`, e.g.
`"chrome"`, `"firefox"`, `"firefox+gnomekeyring"`, `"chromium::Container 1"`.
`cookiefile` must be an existing Netscape-format `cookies.txt`. `proxy` accepts
`http`, `https`, `socks4`, `socks4a`, `socks5`, and `socks5h` URLs. Invalid
values raise `SalinValueError` before any request is made.

The same settings are used for metadata extraction, the direct caption fetch,
the yt-dlp fallback, `fetch()`, and the re-extraction that happens when a
signed track URL expires. `inspect()` and `resolve()` accept them too.

One limitation: `fetch()` reads caption bytes directly with `urllib`, so it
supports only `http://` proxies (the common CONNECT form). With an `https://`,
`socks4`, or `socks5` proxy, `fetch()` raises `SalinValueError` and points you
at `download()`, which hands the fetch to yt-dlp and supports every scheme.

> **Security note:** enabling `cookies` reads from that browser's cookie store
> (encrypted with your OS keyring) and sends your logged-in session to the
> remote site with every request. Only use it when you trust the source, and
> prefer a `cookies.txt` file you control over a browser profile on shared
> machines.

## Performance notes

- **One extraction per video.** Metadata extraction is ~4s and dominates wall
  time; the caption bytes are ~0.3s. Reuse `info=` across `inspect`/`resolve`/
  `fetch`/`download` (see [One metadata fetch per call](#one-metadata-fetch-per-call)).
- **Pooled yt-dlp clients.** `extract_info()` keeps one `yt-dlp` client per
  thread and per request-config, so back-to-back calls reuse the connection and
  skip the ~0.3s client setup. A repeated extract drops from ~3.0s to ~1.2–1.6s
  in our measurements.
- **Bounded retries.** `yt-dlp`'s defaults are patient; Salin caps
  `retries`, `extractor_retries`, and `socket_timeout` so a stuck request
  fails fast instead of stalling a batch.

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
