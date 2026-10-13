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


class UnsupportedFormatError(YtSubsError, NotImplementedError):
    """Raised when a subtitle format has no parser for the requested operation."""
