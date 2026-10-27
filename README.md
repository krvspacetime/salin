# yt-subs

`yt-subs` is a small Python library for inspecting, resolving, downloading, and
cleaning YouTube subtitle tracks.

## Install

To add as dependency using `uv`:

```bash
uv add git+https://github.com/krvspacetime/yt-subs.git
```

## Basic Usage

```python
from yt_subs import YtSubs
client = YtSubs(languages="en")
result = client.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
# If `output_dir` is not specified, subtitles are saved to ./yt_subs_downloads
# Override default by specifying output_dir to the client or in `download` or `download_many`
```

Specify format.

```python
client = YtSubs()
result = client.download(
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    subtitle_format="vtt")
```

Download more than one language:

```python
client = YtSubs(languages=["en", "de"])
result = client.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
print(result)
SubtitleResult(
    url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    video_id='dQw4w9WgXcQ',
    title='Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)',
    subtitles=
        (SubtitleFile(
            requested='en',
            resolved='en',
            source=<SubtitleSource.MANUAL: 'manual'>,
            status=<DownloadStatus.OK: 'ok'>, 
            sub_path=WindowsPath('yt_subs_downloads/dQw4w9WgXcQ.en.vtt'),
            format=<SubtitleFormat.VTT: 'vtt'>,
            error=None),
        SubtitleFile(
            requested='de',
            resolved='de-DE',
            source=<SubtitleSource.MANUAL: 'manual'>, 
            status=<DownloadStatus.OK: 'ok'>, 
            sub_path=WindowsPath('yt_subs_downloads/dQw4w9WgXcQ.de-DE.vtt'),
            format=<SubtitleFormat.VTT: 'vtt'>, 
            error=None)))
```
## Fetch transcripts in memory

`fetch()` is the `youtube-transcript-api`-shaped path: it returns snippets
directly, writes no file, and does not download the video.

```python
from yt_subs import YtSubs

transcript = YtSubs(languages="en").fetch("dQw4w9WgXcQ")
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

### Migrating from youtube-transcript-api

```diff
- from youtube_transcript_api import YouTubeTranscriptApi
- transcript = YouTubeTranscriptApi().fetch(video_id, languages=("en",))
+ from yt_subs import YtSubs
+ transcript = YtSubs(languages="en").fetch(video_id)
```

```python
from yt_subs import FetchedTranscript, TranscriptSnippet
```

Differences to know about:

- `fetch()` takes the language list in the `YtSubs(...)` constructor (or a
  `languages=` override), not as a positional argument.
- Snippets are **normalized**: inline markup, speaker chevrons (`>>`), and
  stage directions such as `[Music]` are stripped, and whitespace is
  collapsed. `youtube-transcript-api` only strips HTML tags, so text can
  differ slightly for captions that contain those markers.
- `preserve_formatting=True` is not supported and raises `YtSubsValueError`.
- Failures raise yt-subs errors: `TranscriptUnavailableError` when no
  requested language resolves, and `SubtitleDownloadError` when the caption
  request itself fails.
- A `429` raises `RateLimitedError` (a `SubtitleDownloadError` subclass) with
  `.retry_after` set from the server's `Retry-After` header when present.

## Inspect subtitles

Inspect shows the available auto and manual subs as well as their available formats.

```python
client = YtSubs()
result = client.inspect(url)
print(result)
SubtitleAvailability(
    url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    video_id='dQw4w9WgXcQ',
    title='Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)',
    manual=frozenset({'pt-BR', 'es-419', 'de-DE', 'en', 'ja'}),
    auto=frozenset({'en', 'en-orig'}),
    manual_formats={'en': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), 'de-DE': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), 'ja': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), 'pt-BR': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), 'es-419': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'})},
    auto_formats={'en-orig': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'}), 'en': frozenset({'srv3', 'srt', 'srv1', 'vtt', 'srv2', 'ttml', 'json3'})})
```

## Resolve Available Subtitles

Resolve gives the `ResolvedSubtitle` containing the actual `resolved` track according to the requested, source policy and language match params.

```python
client = YtSubs()
result = client.resolve(
    url,
    language_match="exact", #LanguageMatch.EXACT
    source_policy="manual_only", #SubtitleSourcePolicy.MANUAL_ONLY
    languages={"en": ["en-US", "en-GB"], "de": ["de-DE", "de-AT"]},
)
print(result)
(ResolvedSubtitle(requested='en', resolved='en', source=None), ResolvedSubtitle(requested='de', resolved=None, source=None))
```
If `resolved` is `None`, it means the resolver was not able to resolve the requested language track according to the availablity, language match and source policy.

## Language match and source policy

Both of them honor each other. For example if language_match is set to "exact" but source_policty is "auto_only", the client will ignore (not download) a requested "en" track even if it's technically available as a manual track.

```python
LanguageMatch.EXACT # "en" only resolves to "en"
LanguageMatch.REGIONAL # "en" can resolve to en-US, en-orig, etc.

SubtitleSourcePolicy.MANUAL_ONLY
SubtitleSourcePolicy.AUTO_ONLY
SubtitleSourcePolicy.MANUAL_THEN_AUTO
SubtitleSourcePolicy.AUTO_THEN_MANUAL
```

## One metadata fetch per call

`inspect()`, `resolve()`, `fetch()`, and `download()` each fetch the video's
metadata once.
That fetch averages ~4 seconds and is about 98% of a download's wall time; the
subtitle bytes themselves are ~0.3s. Calling all three on one video costs
roughly 12s, almost all of it the same metadata fetched three times.

`download()` already resolves languages and reports every requested language,
so most flows need a single call:

```python
result = client.download(url)
for subtitle in result.subtitles:
    print(subtitle.requested, subtitle.resolved, subtitle.status)
```

When you do need the intermediate stages, reuse the metadata with `info=`.
`extract_info()` is exported for exactly this:

```python
from yt_subs import extract_info

info = extract_info(url)                                # one request per video
availability = client.inspect(url, info=info)
resolved = client.resolve(url, languages=["en", "de"], info=info)
transcript = client.fetch(url, languages="en", info=info)
result = client.download(url, languages=["en", "de"], info=info)
```

Measured on the same video: the shared pipeline is one extraction (~4s) plus
~0.6s of work, versus ~12s for three independent calls.

`info` must be a dict returned by `extract_info()`. Hand-built dicts are
rejected — yt-dlp needs the full record (`id`, `extractor`, and the subtitle
tracks) to download anything, so a trimmed dict would fail much later. Playlist
results are rejected too; `yt-subs` downloads single videos only.

## Clean transcripts

`download()` gives you the subtitle file exactly as YouTube serves it. That file
is a poor thing to read, index, or feed to a model, and `clean_transcript()`
turns it into prose.

### Why

Auto-generated captions carry two kinds of noise. Captions are written as they
are spoken, in short overlapping windows, so the same phrase lands on screen
three times in a row:

```
00:48:18.950 --> 00:48:18.960 align:start position:0%
multiple hours to capture the same level

00:48:18.960 --> 00:48:20.710 align:start position:0%
multiple hours to capture the same level
of<00:48:19.119><c> mistake</c><00:48:19.520><c> because</c><00:48:20.000><c> it</c><00:48:20.240><c> requires</c><00:48:20.560><c> like</c>

00:48:20.710 --> 00:48:20.720 align:start position:0%
of mistake because it requires like
```

Those three cues are on screen *simultaneously* -- a scrolling window, not three
successive statements. Read in file order, "multiple hours to capture the same
level" and "of mistake because it requires like" each appear twice, plus the
inline `<00:48:19.119><c>` word-timing tags are not text at all.

On top of that, YouTube's caption formats are display markup rather than prose:

```xml
<p t="1360" d="1680">[♪♪♪]</p>
<p t="18640" d="3240">♪ We&#39;re no strangers to love ♪</p>
<p t="22640" d="4320">♪ You know the rules<br />and so do I ♪</p>
```

Cleaning does three things: strips display markup and stage directions
(`[Music]`, `(laughter)`, `>>` speaker chevrons, music notes), merges the
overlapping windows, and returns one paragraph.

### What you get

The three cues above become:

```
multiple hours to capture the same level of mistake because it requires like
```

and the `srv3` file becomes:

```
We're no strangers to love You know the rules and so do I
```

To write those out:

```python
from yt_subs import YtSubs, clean_transcript

result = YtSubs(languages="en", subtitle_format="vtt").download(url)
paths = clean_transcript(result, output_dir="transcripts")
```

With `output_dir` omitted, each transcript is written next to its source
subtitle. `max_workers` cleans in parallel (default `1`).

To get the text without touching the filesystem, use `clean_cues()`:

```python
from yt_subs import clean_cues

subtitle = result.ok_subs[0]
text = clean_cues(subtitle.sub_path, subtitle.format)
```

Every `SubtitleFormat` is parsed: `vtt`, `srt`, `json3`, `srv1`, `srv2`, `srv3`,
and `ttml`. Add another in `yt_subs/cleaner/parsers/` and register it in
`CUE_READERS`.

### VTT is approximate

Six of the seven formats are exact. `vtt` is not, and the difference is small:
on a 72-minute auto-captioned podcast the cleaned `vtt` transcript came out 41
words longer than the same video's other six formats (15734 vs 15693, 0.3%).

Auto-caption `vtt` is the only rolling format, and YouTube sometimes repeats a
word *inside* a single cue, where the overlap merge cannot see it:

```
cue: startup world in Belgium. I did that for for a little while and then moved to
```

The cleaner cannot tell that seam artifact from a genuine stumble like `or or` or
`it it`, both of which are real and appear in every format, so it leaves both
alone. This only affects auto-generated captions, and only `vtt`; manually
authored tracks are usually not rolling. If you need the exact text, prefer
`srt`, `srv1`, `srv3`, `json3` or `ttml`.

## Bulk Downloads

`download_many()` returns `Iterator[SubtitleResult]` so it's recommended for bulk downloads. It is implemented using `ThreadPoolExecutor` so the `max_workers` can be set (defaults to 1).

> Note: `download_many` is both faster and more memory efficient than simply calling `download` for every URL. Results are yielded as they finish, so it does not preserve input order unless `max_workers=1`.

```python
client = YtSubs()

results = client.download_many(urls, languages="en", max_workers=3):
for result in results:
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

## Throttling

`yt-subs` adds no artificial delay by default: `sleep_interval_subtitles`
defaults to `0` (the same default yt-dlp uses for its own
`--sleep-interval-subtitles`). Subtitle tracks are one small request each, and
the extra track requests are not what YouTube throttles.

Raise the interval if request volume is your bottleneck instead:

```python
client = YtSubs(languages=["en", "de", "ja", "pt-BR"], sleep_interval_subtitles=2)
```

Each extra language then costs `(languages - 1) x interval` seconds of sleep —
with 4 languages and the old default of 2s that was 6s of dead time per video
against roughly 5s of real work. `sleep_interval_requests` is forwarded to
yt-dlp and only applies when yt-dlp itself performs the download.

### When YouTube rate-limits you

YouTube enforces a shared limit on the `timedtext` caption endpoint that is
independent of yt-dlp's page requests. When it trips, the request comes back
`HTTP 429`, and yt-subs records it as a distinct status instead of a generic
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
from yt_subs import RateLimitedError

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
client = YtSubs(
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
values raise `YtSubsValueError` before any request is made.

The same settings are used for metadata extraction, the direct caption fetch,
the yt-dlp fallback, `fetch()`, and the re-extraction that happens when a
signed track URL expires. `inspect()` and `resolve()` accept them too.

One limitation: `fetch()` reads caption bytes directly with `urllib`, so it
supports only `http://` proxies (the common CONNECT form). With an `https://`,
`socks4`, or `socks5` proxy, `fetch()` raises `YtSubsValueError` and points you
at `download()`, which hands the fetch to yt-dlp and supports every scheme.

> **Security note:** enabling `cookies` reads from that browser's cookie store
> (encrypted with your OS keyring) and sends your logged-in session to the
> remote site with every request. Only use it when you trust the source, and
> prefer a `cookies.txt` file you control over a browser profile on shared
> machines.
