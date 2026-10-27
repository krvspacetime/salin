# Competitive notes: making `yt-subs` a serious alternative to `youtube-transcript-api`

`youtube-transcript-api` (yta) is MIT, ~8.5k stars, actively maintained
(last push 2026-10-20). It is the default choice because it is small, returns
in-memory snippets, and is easy to install. `yt-subs` is technically stronger
in several places, but most of that strength is invisible to a yta user
evaluating the README for 60 seconds.

The benchmark (`bench/RESULTS.md`) changes the positioning in one important
way: **yt-subs is not immune to YouTube rate limits.** It survives the
watch-page block that kills yta (479/480 captioned videos over 43.5 minutes,
zero blocks, at ~11 videos/min), but caption bytes come from the same
`timedtext` endpoint and get 429'd too — one burst from yta took it down
completely. The defensible claim is narrower and more useful: *yt-subs still
inspects and resolves when yta is blocked, and at a sustainable pace it keeps
fetching captions long after yta has died.*

Below, P0 items are adoption blockers, P1 items are differentiators, P2 is
polish.

## Status (updated 2026-10-27)

- **#1 License → MIT**: done. `LICENSE`, `pyproject.toml`, and the built
  wheel metadata now say MIT.
- **#3 `fetch()`**: done. `YtSubs.fetch()` returns a yta-shaped
  `FetchedTranscript` from the `json3` track, in memory, with no file write.
- **#4 cookies / `cookiefile` / proxy**: done. `extract_info`, the direct
  caption fetch, the yt-dlp fallback, `fetch()`, and the 403 re-extract all
  take the same request config. `cookiefile` (Netscape format) and `proxy`
  are now accepted alongside `cookies`. `fetch()` requires an `http://` proxy
  because it fetches with `urllib`; SOCKS and `https://` proxies work through
  `download()`, which uses yt-dlp's networking.
- **#5 rate-limit errors**: done. `DownloadStatus.RATE_LIMITED`,
  `RateLimitedError(retry_after=...)`, `Retry-After` parsing, bounded
  5xx/connection retries, one 403 refresh, `strict=True`, and a
  `download_many` breaker.
  **Deviation:** there is no `stopped_reason="rate_limited"` return value.
  `download_many` is a generator, so it simply ends when
  `max_consecutive_rate_limits=N` trips; callers count what they consumed or
  inspect the `RATE_LIMITED` statuses.
- **#6 repo hygiene + CI**: done. `.env` secret guard, `testpaths=["tests"]`,
  a pinned ruff target with a wider lint set, `py.typed`, `__version__` from
  `importlib.metadata`, and `.github/workflows/ci.yml` running ruff,
  `ruff format --check`, `ty check`, pytest and `uv build` on 3.12/3.13.
- **#9 speed work**: partly done. The `process=False` idea was measured and
  **rejected** — identical output, no wall-time gain (3.1–3.3s either way). A
  thread-local `YoutubeDL` pool was adopted instead: one client per thread per
  request-config, so a repeated extract drops from ~3.0s to ~1.2–1.6s. HTTP
  session reuse and metadata caching are still open.
- **#11 README rewrite**: done. Centered header with badges, the yta comparison
  table, the rate-limit story, a performance section, and a dev/CI section.
- Everything else is still open. Suggested order at the bottom of this file.

---

## P0 — fix before promoting it

### 1. License: AGPL-3.0 is a adoption blocker

`LICENSE` is AGPL-3.0. yta is MIT. Many companies and open-source projects
ban AGPL outright, and a library that is imported into another program is
exactly where AGPL's network-copyleft is scariest. If the goal is to be a
drop-in alternative, relicense to **MIT** (simplest) or **Apache-2.0**
(patent grant). yt-dlp is Unlicense, so there is no conflict. Do this before
anyone depends on the current license.

### 2. Publish to PyPI

The install instructions are `uv add git+https://...`, which loses almost
everyone who is not already committed. `yt-subs` is free on PyPI (`ytsubs`
is taken). Add:

```toml
[project]
license = "MIT"
authors = [{ name = "..." }]
keywords = ["youtube", "subtitles", "transcripts", "captions", "yt-dlp"]
classifiers = [
  "Development Status :: 4 - Beta",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.12",
  "Topic :: Multimedia :: Video",
  "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/krvspacetime/yt-subs"
Issues = "https://github.com/krvspacetime/yt-subs/issues"
Changelog = "https://github.com/krvspacetime/yt-subs/blob/main/CHANGELOG.md"

[project.scripts]
ytsubs = "yt_subs.cli:main"
```

Then `uv build` + `uv publish` (or PyPI trusted publishing from GitHub
Actions). Keep the `ytsubs` command name even if the package stays `yt-subs`.

### 3. Add an in-memory `fetch()` with yta's shape

This is the single highest-value API addition. yta users do:

```python
transcript = YouTubeTranscriptApi().fetch(video_id, languages=("en",))
for snippet in transcript:
    print(snippet.start, snippet.text)
```

`yt-subs` currently forces a file write and returns a `SubtitleResult` tree.
That is great for ETL, but it is not the 80% use case. Add:

```python
from yt_subs import YtSubs

transcript = YtSubs(languages="en").fetch("dQw4w9WgXcQ")
transcript.video_id, transcript.language_code, transcript.is_generated
for snippet in transcript:              # text, start, duration
    ...
transcript.to_raw_data()                # list[dict], same as yta
transcript.text                         # cleaned prose
```

Return the same dataclass shape as yta:

```python
@dataclass(frozen=True, slots=True)
class TranscriptSnippet:
    text: str
    start: float
    duration: float

@dataclass(frozen=True, slots=True)
class FetchedTranscript:
    snippets: tuple[TranscriptSnippet, ...]
    video_id: str
    language: str
    language_code: str
    is_generated: bool

    def __iter__(self): ...
    def __getitem__(self, i): ...
    def __len__(self): ...
    def to_raw_data(self) -> list[dict]: ...
```

Implementation sketch:

1. `extract_info(url, process=False)` (see speed below).
2. Resolve languages exactly as `download()` does.
3. Pick the `json3` track (`SubtitleFormat.JSON3`) — it has clean event
   timings and no rolling-overlap ambiguity.
4. Fetch the bytes in memory (no temp file).
5. `parse_json3_cues(source)` → `ParsedCue(start_ms, end_ms, text)`.
6. Return snippets with `start = start_ms / 1000`,
   `duration = (end_ms - start_ms) / 1000`.

Do **not** write a file for `fetch()`. Keep `download()` for files. This also
makes `fetch()` faster and safer (no path handling).

Do not promise full class-level drop-in (`TranscriptList`, `find_transcript`,
`translate`). Matching the returned object plus `fetch()` covers most real
code. Publish a short migration guide instead:

```diff
- from youtube_transcript_api import YouTubeTranscriptApi
- transcript = YouTubeTranscriptApi().fetch(video_id)
+ from yt_subs import YtSubs
+ transcript = YtSubs(languages="en").fetch(video_id)
```

### 4. Cookies are broken for metadata extraction (done)

`YtSubs(cookies="chrome")` only passes cookies to the yt-dlp subtitle
fallback. `inspect()`, `resolve()`, and `download()` call
`extract_info(url)` with no cookies, so age-restricted/region-locked videos
fail before the cookie is ever used. `_download_subtitles_direct()` also
ignores cookies.

Fix `extract_info` to accept the same `cookies`/`cookiefile`/`proxy`
arguments and thread them through every call site. Add `cookiefile` support
too: the README recommends a `cookies.txt` you control, but there is no way
to pass one. The client currently only accepts browser specs.

```python
YtSubs(cookies="chrome")
YtSubs(cookiefile="cookies.txt")     # missing today
YtSubs(proxy="http://...")           # missing today
```

### 5. Rate limits need a first-class error, not `MISSING` (done)

In the benchmark, every 429 became `status=missing` or `status=error` with a
raw yt-dlp string. Worse, the direct fetch falls back to yt-dlp on 429,
which retries with backoff (we saw 25s, 45s, 67s, 88s per video). A blocked
batch of 100 took 19 minutes and looked like "no transcripts."

- Add `DownloadStatus.RATE_LIMITED` and `RateLimitedError(retry_after=...)`.
- In `_fetch_subtitle_bytes`, catch `HTTPError` before the generic fallback:
  - `429`: raise `RateLimitedError`; **do not** fall back to yt-dlp.
  - `403`: the signed URL may have expired; re-extract once, then fall back.
  - `5xx`: retry with jitter.
- Add `strict=True` so `download()` raises instead of returning a status.
- In `download_many`, stop after N consecutive rate-limit errors with
  `max_consecutive_rate_limits=N`; do not keep hammering. A generator cannot
  return a `stopped_reason`, so the run simply ends and the caller inspects how
  many results it consumed.
- Set `retries`, `extractor_retries`, and `socket_timeout` explicitly.
  yt-dlp's defaults are too patient for a batch library.
- Parse `Retry-After` and honour it.

This turns the benchmark's worst finding into a differentiator: *the library
that tells you when YouTube is rate-limiting you and stops cleanly.*

### 6. Fix the repo hygiene that breaks contributors

- `yt-subs-dev/` is untracked but `pytest` and `ruff` walk into it. Current
  `uv run pytest -q` fails with `import file mismatch`; `uv run pytest tests`
  passes 135 tests. Add `[tool.pytest.ini_options] testpaths = ["tests"]`
  and either delete or gitignore the dev copy.
- `.env` was untracked and not ignored; it is now ignored. Keep it that way.
- Add `.github/workflows/ci.yml`: ruff, `ty`, pytest on 3.12/3.13, `uv build`.
- Add `yt_subs/py.typed` and `Typing :: Typed`.
- Add `__version__` from `importlib.metadata`.

---

## P1 — what makes it actually better

### 7. A CLI, but after `fetch()`

Yes, build a CLI. It is the best demo, the best benchmark harness, and the
only way non-Python users can try the tool. But build it on top of `fetch()`,
not before it — otherwise the CLI has to parse files itself.

Proposed surface:

```bash
ytsubs fetch URL [URL...] -l en --format text|json|srt|vtt
ytsubs bulk ids.txt -l en --workers 3 --format jsonl --out transcripts/ \
  --resume --skip-existing --cookies-from-browser chrome
ytsubs inspect URL --json
ytsubs clean transcripts/ --format vtt
ytsubs doctor
```

- `--format text` → cleaned prose to stdout (pipe-friendly).
- `--format json` → the yta-shaped object, one record.
- `--format jsonl` → one record per video with `ok`, `error`, `language`,
  `text`, `snippets`.
- Exit codes: `0` all ok, `1` partial, `2` usage, `3` rate-limited,
  `4` no transcript.
- `doctor`: yt-dlp age, Python, cookie/proxy config, and a one-video smoke
  test. This will save you a lot of support time.

Use `argparse` to keep the dependency footprint small; `typer` is fine if
you prefer it.

### 8. `inspect_many`, `skip_existing`, atomic writes

Your user's DB pipeline wants availability for thousands of videos. Add:

```python
client.inspect_many(urls, max_workers=3)   # Iterator[SubtitleAvailability]
```

`download()` should skip files that already exist (`skip_existing=True`) and
write atomically (temp file + `os.replace`) so a Ctrl-C never leaves a
truncated `.vtt`. Both are small changes with large bulk-workflow value.

### 9. Objective speed work

Measured on 6 videos:

| change | median metadata time |
|---|---:|
| current (`process=True`) | 1.96s |
| `extract_info(..., process=False)` | 1.48s |
| reused `YoutubeDL` | 1.52s (vs 1.80s new) |

- **`process=False`**: ~25% faster, still returns all caption tracks. Use it
  for `inspect`/`resolve`/`fetch` and the direct-download path. Keep
  `process=True` only for the yt-dlp download fallback (or let
  `process_ie_result` process it).
- **Reuse `YoutubeDL`**: ~15% faster, but not documented as thread-safe;
  use one per thread/worker.
- **Reuse an HTTP session** for `timedtext` (`requests.Session` or a shared
  opener) to avoid a TLS handshake per video. This also gives you free
  connection pooling, proxy support, and `urllib3.Retry`.
- **Cap retries.** A single 190s metadata outlier in our probe came from
  yt-dlp retrying. Set `extractor_retries=1`, `retries=2`,
  `socket_timeout=15` and surface the failure.
- **Cache extracted metadata** in memory (and optionally on disk with a TTL).
  Signed caption URLs expire, so cache the track list and refresh on 403.
- Re-run the `max_workers` table after these changes; the old 2–3 ceiling
  was measured when metadata was ~4s and may move.

### 10. Translation and language coverage

`is_native_auto_caption_track()` deliberately drops `tlang` tracks, so
`yt-subs` cannot return YouTube's auto-translated captions. yta can
(`transcript.translate("es")`). Add `translate_to=` / `--translate-to` by
selecting the `tlang` track, and document the difference between a manual
track, a native auto track, and a translated auto track.

Also add language aliases (`iw`↔`he`, `in`↔`id`, `zh`↔`zh-Hans`) and
normalize casing/underscores. These are cheap wins for non-English users.

### 11. Docs that sell the difference

The README is good but leads with API reference. Add, above the fold:

- A one-paragraph "why this exists" with the block story.
- A comparison table:

| | yta | yt-subs |
|---|---|---|
| In-memory snippets | yes | add `fetch()` |
| File output | no | yes (7 formats) |
| Cleaning/dedup | no | yes |
| Language resolution policies | limited | manual/auto, regional variants |
| Bulk API | no | `download_many`, `inspect_many` |
| Cookies/proxy | proxy yes | cookies browser-only today; fix |
| Survives watch-page IP block | no | yes (metadata still works) |
| Explicit rate-limit errors | `IpBlocked` | add `RateLimitedError` |
| CLI | no | add |
| License | MIT | AGPL today — change |
| Python | 3.9+ | 3.12+ |

- A benchmark section with the table from `bench/RESULTS.md`, the date, the
  yt-dlp version, and the caveat that timedtext is shared. Honesty here is a
  differentiator; overclaiming "never blocked" will be disproved in a day.
- A "when you will still get blocked" section: cookies, proxies, pacing,
  and the `429` behavior.
- A migration guide from yta.

Also fix the README's `download_many` example (stray `:` and the
`language=` vs `languages=` typo), and update the "Throttling" section: it
currently says extra track requests are not what YouTube throttles, which
the benchmark contradicts.

### 12. Productize the indexing extension

`yt-subs-dev/yt_subs/extensions/indexing/` already contains Postgres FTS
schema and RPC. That is a much bigger differentiator than another downloader:
"transcripts in, searchable Postgres out." If you productize it, `yt-subs`
becomes the ETL layer for transcript search, not just a yta replacement.
Keep it optional (`yt-subs[indexing]`) so the core stays small.

---

## P2 — polish

- Lower `requires-python` to 3.11 or 3.10 if feasible. `StrEnum` (3.11) and
  `type` aliases (3.12) are the only blockers; 3.12-only excludes a lot of
  data pipelines. yta supports 3.9+.
- Consider depending on plain `yt-dlp` rather than `yt-dlp[default]`; the
  extra pulls in websockets, mutagen, pycryptodomex, etc. Test subtitle
  downloads with the core package.
- Add `output_template` (`{id}.{lang}.{ext}` is fixed today) and
  `overwrite`/`skip_existing`.
- Add a progress callback or `on_result` hook for CLI progress bars.
- Add `to_json()`/`from_json()` and a stable JSON schema for the CLI.
- Add coverage and a nightly canary against 1–2 known videos.
- Add a `CITATION.cff`, changelog, and semantic versioning.
- Add a `docs/` site (mkdocs-material) with API reference and recipes:
  Postgres ingest, SRT export, LLM summarization, FTS search.
- Add examples for FastAPI/Flask endpoints and Airflow/Prefect tasks.

---

## Naming

Constraints: English, Spanish, French, or Tagalog; short; typeable; available
on PyPI; works as a CLI command; not embarrassing in any of those languages.

### Candidate marks

The README header uses a neutral mark in `assets/logo.svg`, so the repo does
not depend on the final name:

<p align="left"><img src="assets/logo.svg" width="72" alt="neutral mark"></p>

The three names still in play, as ready-to-drop icons:

| Tinig | Salin | SubtitleKit |
|:---:|:---:|:---:|
| <img src="assets/tinig.svg" width="72" alt="Tinig"> | <img src="assets/salin.svg" width="72" alt="Salin"> | <img src="assets/subtitlekit.svg" width="72" alt="SubtitleKit"> |
| waveform — voice | overlaid cards — translation/copy | stacked layers — toolkit |

When you commit to a name, copy its icon over `assets/logo.svg` and point the
README header at it; the other two can be deleted.

PyPI status checked 2026-10-27:

| name | language | meaning | PyPI | domains (A record) | notes |
|---|---|---|---|---|---|
| **Hango** | Tagalog | derived/extracted from | free | `.dev` free; `.io`/`.com` taken | best semantic fit, 5 letters, unique, no false friends |
| **Tinig** | Tagalog | voice | free | `.dev`/`.io` free; `.com` taken | beautiful, 5 letters; less explicit about text |
| **Titik** | Tagalog | letter/writing | free | `.dev`/`.io` free; `.com` taken | alliterative with "text"; "titik" = dot in Malay/Indonesian |
| **Saysay** | Tagalog | meaning/narrative | free | all taken | unique; pronunciation less obvious |
| **Basahin** | Tagalog | to read | free | `.dev`/`.io` free; `.com` taken | clear verb, 7 letters |
| **Subtitula** | Spanish | subtitle it (imperative) | free | `.dev`/`.io`/`.com` free | instantly clear to ES/PT speakers; 9 letters; best domain availability |
| **Subtexto** | Spanish | subtext | free | `.dev`/`.io` free; `.com` taken | double meaning; common English word, trademark risk |
| **Verbe** | French | word/verb | free | `.dev` free; `.io`/`.com` taken | elegant, 5 letters; English speakers hear "verb" |
| **SubtitleKit** | English | subtitle toolkit | free | `.dev`/`.io` free; `.com` taken | safe, professional, SEO-friendly; generic, hard to trademark |
| **Captionist** | English | one who captions | free | `.dev`/`.io` free; `.com` taken | human/professional; implies authoring |
| **TranscriptKit** | English | transcript toolkit | free | `.dev`/`.io` free; `.com` taken | clear, professional; long |
| **Subfetch** | English | fetch subs | free | `.dev`/`.io` free; `.com` taken | CLI-friendly; sounds like a downloader |

More Tagalog options (checked 2026-10-27; `PyPI` via the JSON API, `.dev/.io/.com`
via A-record lookup, so a "free" domain could still be registered without an
A record):

| name | meaning | PyPI | domains | notes |
|---|---|---|---|---|
| **Tinig** | voice | free | `.dev`/`.io` free | *your current pick*; elegant, 5 letters, fits captions |
| **Salin** | translation, copy | free | `.io` free | most on-the-nose meaning for subtitles; 5 letters |
| **Bigkas** | utterance, pronunciation | free | `.dev`/`.io` free | precise for captions; 6 letters |
| **Sulyap** | glimpse, glance | free | `.dev`/`.io` free | evocative of reading along; 6 letters |
| **Pahayag** | statement, declaration | free | `.dev`/`.io` free | captions as statements; 7 letters |
| **Tugon** | response, reply | free | `.dev`/`.io` free | short, clean; 5 letters |
| **Bulong** | whisper | free | `.dev`/`.io` free | soft, memorable; 6 letters |
| **Talata** | paragraph | free | `.dev`/`.io` free | structure-of-text meaning; 6 letters |
| **Liham** | letter, written message | free | `.dev`/`.io` free | text-forward; 5 letters |
| **Pahina** | page | free | `.dev`/`.io` free | text-forward; 6 letters |
| **Tugma** | rhyme, match, fit | free | `.dev`/`.io` free | ties to cue matching; 5 letters |
| **Liwanag** | light, clarity | free | `.dev`/`.io` free | pretty; 7 letters; less specific |
| **Silip** | peek, peep | free | `.dev`/`.io` free | short; playful |
| **Boses** | voice | free | `.dev`/`.io` free | close to Tinig, less elegant |
| **Huni** | chirp, birdsong | free | `.io` free | pretty but vague |
| **Kuwento** | story | free | `.dev` free | narrative flavor; 7 letters |
| **Sambit** | utterance, mention | free | all taken | great meaning, no domains |
| **Tanaw** | view, lookout | free | all taken | great meaning, no domains |
| **Hiwatig** | hint, suggestion | free | `.dev`/`.io`/`.com` free | rare full availability; weaker meaning |
| **Daglat** | abbreviation | free | `.dev`/`.io`/`.com` free | full availability; weak meaning |
| **Diwa** | essence, meaning | free | all taken | beautiful, 4 letters, no domains |
| **Awit** / **Tula** / **Sulat** / **Sipi** / **Himig** / **Wika** | song / poem / writing / excerpt / melody / language | taken | mixed | great words, PyPI already taken |

Avoid: `Salita` (Spanish false friend: "little living room"), `Tala` (taken),
`Parole` (taken; prison-tech association in English), `Plume` (taken),
`Substream` (taken), `yt-subs` long-term (ties you to YouTube's trademark and
limits expansion to other yt-dlp sites).

If you stay with **Tinig**, the practical combo is PyPI `tinig`, CLI `tinig`
(or keep `ytsubs` as the command and `tinig` as the package), domain
`tinig.dev`. Other same-rank picks: **Salin** if you want the meaning to be
obvious to anyone who knows Tagalog, **Bigkas** if you want the most precise
description of what the tool extracts.

Recommendation:

- **Ship now:** publish `yt-subs` on PyPI (it is free), keep the repo name,
  add the `ytsubs` CLI. This is zero-friction and lets you iterate.
- **If you rebrand:** **Hango** is the strongest combination of meaning,
  length, uniqueness, and availability. **Tinig** is the most elegant.
  **SubtitleKit** is the safest English/SEO choice. **Subtitula** is the best
  if your audience is Spanish/Portuguese-first.
- Before committing, check GitHub org/repo, `.dev`/`.io` domain, and a quick
  trademark search in your target markets.

## Should this be a Rust project?

Short answer: **not before the first release, and probably not for the library
at all.** Ship the Python package on PyPI first; treat Rust as an optional CLI
or accelerator later.

The reasoning:

- **Where the time goes.** A download is ~4s of metadata extraction plus ~0.3s
  of subtitle bytes, and both are network-bound inside yt-dlp. The Python in
  `yt-subs` is orchestration, language resolution, and text cleaning — CPU work
  that is nowhere near the profile. Rewriting it in Rust would not make
  downloads faster, so there is no performance case.
- **The hard part is not yours, and it is in Python.** The fragile work — the
  player API, signatures, PO tokens, extractor maintenance — lives in yt-dlp.
  A Rust rewrite has only two options, and both are worse than what you have:
  1. **Shell out to the yt-dlp binary** and parse its JSON. You keep the
     dependency treadmill (and now also need Python at runtime unless you bundle
     a whole Python + yt-dlp environment), and you give up the library-level
     `extract_info()` — which is the thing that lets you inspect, resolve, and
     reuse one metadata fetch.
  2. **Reimplement extraction in Rust.** That is re-doing yt-dlp's hardest,
     most volatile surface, and it becomes a permanent maintenance job you
     cannot win.
- **Who your users are.** The audience for "subtitle ETL" is Python data
  pipelines, notebooks, and backends. They install from PyPI. A Rust core is a
  nice engineering story but it does not reach anyone new, and it doubles your
  release surface (crates.io + PyPI, two CI matrices, two changelogs).
- **The differentiator is not the language.** It is the honest rate-limit
  handling, the cleaning/dedup, the typed API, and the language-resolution
  policies. All of that is cheap in Python and already written.

Where Rust *does* make sense, and how to sequence it:

1. **Release the Python package now**, under the chosen name, on PyPI. Nothing
   below is worth blocking that.
2. **Optional Rust CLI** (`tinig`/`salin`/`subtitlekit`) that reuses the core
   from your other Rust project and shells out to yt-dlp. This is a genuine
   brand and distribution win — a single static binary, `brew install`, no
   Python runtime — and it is the most attractive Rust path. Keep the Python
   package as the SDK; share the name and the docs site.
3. **Optional PyO3 accelerator** (`maturin`) if — and only if — you can measure
   a real hotspot. Candidates are the dedup/overlap merge and parsing on very
   large transcripts. Measure first; the current cleaning is not slow enough to
   justify a second language in the wheel.

The one trap to avoid: assuming "Rust" means "no dependencies." As long as you
delegate extraction to yt-dlp, you are still shipping or requiring Python.
A truly dependency-free Rust tool means writing your own extractor — which is
exactly the part you do not want to own.

If the goal is the brand, the strongest combination is a Rust **CLI** plus the
Python **SDK** under one name. If the goal is to actually ship, the Python
package is the whole job.

---

## Suggested order of work

Done:

- ~~#1 Relicense to MIT, add PyPI metadata~~ — MIT LICENSE, `license`, authors,
  and project URLs are in `pyproject.toml`; `uv build` emits `License-Expression: MIT`.
- ~~#3 Add `fetch()`~~ — `YtSubs.fetch()` returns a yta-shaped
  `FetchedTranscript` from the `json3` track in memory.
- ~~#4/#5 Rate-limit errors + cookies/proxy~~ — `RATE_LIMITED` status,
  `RateLimitedError`, `Retry-After`, `strict=True`, the `download_many`
  breaker, and `cookies`/`cookiefile`/`proxy` threaded through every request
  path (including the 403 re-extract).
- ~~#6 Repo hygiene + CI~~ — secret guard, `testpaths`, wider ruff rules,
  `py.typed`, `__version__`, and a GitHub Actions workflow.
- ~~#9 Speed work (part 1)~~ — `process=False` measured and rejected; a
  thread-local `YoutubeDL` pool adopted (~3.0s → ~1.2–1.6s on a repeat extract).
- ~~#11 README rewrite~~ — badges, comparison table, rate-limit story,
  performance notes.

Next, in the order I'd do them:

1. **Publish to PyPI (#2).** The package is named and licensed; trusted
   publishing from the CI workflow is the last step to being installable.
2. **Speed work (remaining #9).** A reused HTTP session for `timedtext`, and
   optional on-disk metadata caching with a TTL (cache the track list, refresh
   on 403).
3. **CLI (#7).** `fetch`/`bulk`/`inspect`/`clean`/`doctor`, built on `fetch()`.
   It is the best demo and the best benchmark harness.
4. **`inspect_many` + `skip_existing` + atomic writes (#8)** if you want the
   bulk/ETL story.
5. **Re-run the benchmark (step 7 above)** on a fresh IP, paced vs burst, and
   publish the numbers.
6. Optional later: translation (#10), indexing productization (#12), Python
   floor (#P2), and the Rust CLI / PyO3 accelerator discussed above.

The benchmark harness in `bench/` is reusable for step 6. The key is to run
the clean yt-subs measurement on a fresh IP, and to measure paced vs burst
behavior — that is the number that will make the "better than yta" claim
credible.
