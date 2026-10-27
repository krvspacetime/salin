from importlib.metadata import PackageNotFoundError, version

from .cleaner import clean_cues, clean_transcript
from .client import Salin
from .core import extract_info
from .error import RateLimitedError, SubtitleDownloadError, TranscriptUnavailableError
from .shared.models import LanguageMatch, SubtitleFormat, SubtitleSourcePolicy
from .transcript import FetchedTranscript, TranscriptSnippet

try:
    __version__ = version("salin")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "0.0.0"

__all__ = [
    "Salin",
    "__version__",
    "clean_cues",
    "clean_transcript",
    "extract_info",
    "FetchedTranscript",
    "TranscriptSnippet",
    "RateLimitedError",
    "SubtitleDownloadError",
    "TranscriptUnavailableError",
    "LanguageMatch",
    "SubtitleSourcePolicy",
    "SubtitleFormat",
]
