class YtSubsError(Exception):
    """Base exception for all yt-subs errors."""


class YtSubsValueError(YtSubsError, ValueError):
    """Raised when invalid arguments are provided."""


class LanguageParseError(YtSubsValueError):
    """Raised when language input cannot be parsed or validated."""


class ExtractorError(YtSubsError):
    """Base exception for metadata extraction failures."""


class VideoUnavailableError(ExtractorError):
    """Raised when a video is private, deleted, or unavailable."""


class ChannelUnavailableError(ExtractorError):
    """Raised when a channel or playlist is unavailable or not found."""


class SubtitleDownloadError(YtSubsError):
    """Raised when downloading subtitles fails."""


class RateLimitedError(SubtitleDownloadError):
    """
    Raised when YouTube rate-limits a caption request (HTTP 429).

    ``retry_after`` is the server's ``Retry-After`` value in seconds when it
    sent one, else None. ``video_id`` is set when the caller knows it.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        video_id: str | None = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.video_id = video_id


class TranscriptUnavailableError(YtSubsError):
    """Raised by YtSubs.fetch() when no requested transcript track is available."""

    def __init__(self, video_id: str, message: str):
        super().__init__(message)
        self.video_id = video_id


class UnsupportedFormatError(YtSubsError, NotImplementedError):
    """Raised when a subtitle format has no parser for the requested operation."""
