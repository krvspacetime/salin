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

`inspect()`, `resolve()`, and `download()` each fetch the video's metadata once.
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
result = client.download(url, languages=["en", "de"], info=info)
```

Measured on the same video: the shared pipeline is one extraction (~4s) plus
~0.6s of work, versus ~12s for three independent calls.

`info` must be a dict returned by `extract_info()`. Hand-built dicts are
rejected — yt-dlp needs the full record (`id`, `extractor`, and the subtitle
tracks) to download anything, so a trimmed dict would fail much later. Playlist
results are rejected too; `yt-subs` downloads single videos only.

## Clean transcripts

Auto-generated captions scroll by in overlapping blocks, so the raw file repeats
itself. `clean_transcript()` parses each downloaded subtitle, strips markup and
stage directions (`[Music]`, `(laughter)`, `>>` speaker chevrons), collapses the
rolling overlap, and writes one `.txt` per subtitle.

```python
from yt_subs import YtSubs, clean_transcript

result = YtSubs(languages="en", subtitle_format="vtt").download(url)
paths = clean_transcript(result, output_dir="transcripts")
```

With `output_dir` omitted, each transcript is written next to its source subtitle.
`max_workers` cleans in parallel (default `1`).

To get the text without touching the filesystem, use `clean_cues()`:

```python
from yt_subs import clean_cues

text = clean_cues(result.ok_subs[0].sub_path, result.ok_subs[0].format)
```

Every `SubtitleFormat` is parsed: `vtt`, `srt`, `json3`, `srv1`, `srv2`, `srv3`,
and `ttml`. Add another in `yt_subs/cleaner/parsers/` and register it in
`CUE_READERS`.

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

## Browser Cookies

Some videos only expose subtitles to signed-in clients. `yt-subs` does **not**
touch your browser by default; opt in explicitly if you need age-restricted or
region-locked tracks:

```python
client = YtSubs(languages="en", cookies="firefox:myprofile")
# or per call
result = client.download(url, cookies="chrome")
```

`cookies` uses yt-dlp's syntax: `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`, e.g.
`"chrome"`, `"firefox"`, `"firefox+gnomekeyring"`, `"chromium::Container 1"`.

> **Security note:** enabling this reads cookies from that browser's cookie
> store (encrypted with your OS keyring) and sends your logged-in session to
> the remote site with every request. Only use it when you trust the source,
> and prefer a `cookies.txt` file you control over a browser profile on shared
> machines.
