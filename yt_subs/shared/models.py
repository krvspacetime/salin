from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, NewType, Self, TypedDict


class SubtitleTrack(TypedDict, total=False):
    ext: str
    url: str
    name: str
    protocol: str


class YtdlpVideoInfo(TypedDict, total=False):
    """
    A single video as yt-dlp reports it, i.e. the raw dict returned by
    extract_info(). Nothing is stripped: it also carries formats, chapters
    and thumbnails with signed URLs, and the user's browser cookies when
    cookies are enabled, so treat it as sensitive and do not log or
    serialize it wholesale.

    Every key is optional because yt-dlp fills in ~70 keys and different
    extractors populate different subsets.
    """

    _type: str
    id: str
    extractor: str
    title: str
    subtitles: dict[str, list[SubtitleTrack]]
    automatic_captions: dict[str, list[SubtitleTrack]]


UrlStr = NewType("UrlStr", str)
VideoId = NewType("VideoId", str)
LangCode = NewType("LangCode", str)

type BrowserCookies = tuple[str, str | None, str | None, str | None]


# Requested language code — what the caller asks for, e.g. "en", "zh"
LangCodeRequested = NewType("LangCodeRequested", str)

# Resolved language code — what yt-dlp actually has, e.g. "en-orig", "zh-Hans"
LangCodeResolved = NewType("LangCodeResolved", str)

type LangCodeManual = LangCode
type LangCodeAuto = LangCode


class SubtitleSource(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"


class DownloadStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class SubtitleFormat(StrEnum):
    VTT = "vtt"
    SRT = "srt"
    JSON3 = "json3"
    SRV1 = "srv1"
    SRV2 = "srv2"
    SRV3 = "srv3"
    TTML = "ttml"


# Maps what was requested → what was resolved for download
type LangCodeMap = dict[LangCodeRequested, LangCodeResolved]


@dataclass(frozen=True, slots=True)
class ResolvedSubtitle:
    requested: LangCodeRequested
    resolved: LangCodeResolved | None
    source: SubtitleSource | None

    @property
    def is_resolved(self) -> bool:
        return self.resolved is not None


@dataclass(frozen=True, slots=True)
class SubtitleAvailability:
    url: UrlStr
    video_id: VideoId
    title: str
    manual: frozenset[LangCode]
    auto: frozenset[LangCode]
    manual_formats: dict[LangCode, frozenset[str]]
    auto_formats: dict[LangCode, frozenset[str]]


@dataclass(frozen=True, slots=True)
class SubtitleFile:
    requested: LangCodeRequested
    resolved: LangCodeResolved | None
    source: SubtitleSource | None
    status: DownloadStatus
    sub_path: Path | None = None
    format: SubtitleFormat | None = None
    error: str | None = None
    retry_after: int | None = None

    def __post_init__(self):
        if self.error is not None and self.status not in (
            DownloadStatus.ERROR,
            DownloadStatus.RATE_LIMITED,
        ):
            raise ValueError(
                "error can only be set when status is ERROR or RATE_LIMITED"
            )
        if self.retry_after is not None and self.status != DownloadStatus.RATE_LIMITED:
            raise ValueError("retry_after can only be set when status is RATE_LIMITED")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            requested=data["requested"],
            resolved=data.get("resolved"),
            source=SubtitleSource(data["source"]) if data.get("source") else None,
            status=DownloadStatus(data["status"]),
            sub_path=Path(data["sub_path"]) if data.get("sub_path") else None,
            format=SubtitleFormat(data["format"]) if data.get("format") else None,
            error=data.get("error"),
            retry_after=data.get("retry_after"),
        )


@dataclass(frozen=True, slots=True)
class SubtitleResult:
    url: UrlStr
    video_id: VideoId
    title: str
    subtitles: tuple[SubtitleFile, ...]

    @property
    def ok_subs(self) -> tuple[SubtitleFile, ...]:
        """Returns a tuple of subtitle files that have been successfully downloaded."""
        return tuple(
            s
            for s in self.subtitles
            if s.status == DownloadStatus.OK and s.sub_path is not None
        )

    @property
    def rate_limited_subs(self) -> tuple[SubtitleFile, ...]:
        """Subtitles that failed because YouTube rate-limited the request."""
        return tuple(
            s for s in self.subtitles if s.status == DownloadStatus.RATE_LIMITED
        )

    @property
    def is_rate_limited(self) -> bool:
        """True when any requested subtitle hit the rate limit."""
        return bool(self.rate_limited_subs)

    @property
    def retry_after(self) -> int | None:
        """The largest ``Retry-After`` seen across rate-limited subtitles."""
        values = [
            s.retry_after for s in self.rate_limited_subs if s.retry_after is not None
        ]
        return max(values) if values else None

    @property
    def processable(self) -> Self | None:
        """
        Return a copy of self containing only the subtitles with 'ok' status.
        """
        ok_subs = self.ok_subs
        if not ok_subs:
            return None
        return replace(self, subtitles=ok_subs)

    def __iter__(self) -> Iterator[SubtitleFile]:
        return iter(self.subtitles)

    def __post_init__(self):
        if not isinstance(self.subtitles, tuple):
            object.__setattr__(self, "subtitles", tuple(self.subtitles))

        if not all(isinstance(s, SubtitleFile) for s in self.subtitles):
            raise TypeError("All subtitles must be SubtitleFile instances")

    def to_dict(self) -> dict:
        """Converts the dataclass to a dictionary, turning Path objects into strings."""

        def json_field_factory(kv_pairs):
            return {k: (str(v) if isinstance(v, Path) else v) for k, v in kv_pairs}

        data = asdict(self, dict_factory=json_field_factory)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Self:
        subtitle_files = data.get("subtitles", [])
        cls_keys = {k for k in cls.__annotations__ if k != "subtitles"}
        filtered_data = {k: v for k, v in data.items() if k in cls_keys}
        return cls(
            subtitles=tuple(SubtitleFile.from_dict(s) for s in subtitle_files),
            **filtered_data,
        )


class DownloadOverrides(TypedDict, total=False):
    languages: LanguagesInput | None
    output_dir: Path | str | None
    subtitle_format: SubtitleFormat | str | None
    skip_video: bool | None
    sleep_interval_subtitles: int | None
    sleep_interval_requests: int | None
    language_match: LanguageMatch | None
    source_policy: SubtitleSourcePolicy | None
    cookies: str | None
    cookiefile: Path | str | None
    proxy: str | None
    strict: bool


class LanguageMatch(StrEnum):
    EXACT = "exact"
    REGIONAL = "regional"


class SubtitleSourcePolicy(StrEnum):
    MANUAL_ONLY = "manual_only"
    AUTO_ONLY = "auto_only"
    MANUAL_THEN_AUTO = "manual_then_auto"
    AUTO_THEN_MANUAL = "auto_then_manual"


type LanguagesInput = (
    str
    | dict[str, str | Iterable[str]]
    | Iterable[str | dict[str, str | Iterable[str]]]
)


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    """A requested language and optional ordered regional variants to try."""

    requested: LangCodeRequested
    variants: tuple[LangCodeResolved, ...] = ()

    @property
    def has_variants(self) -> bool:
        return bool(self.variants)
