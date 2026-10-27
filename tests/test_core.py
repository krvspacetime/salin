import pytest
import yt_dlp

from salin import Salin
from salin.core.extractor import extract_info
from salin.core.resolver import resolve_subtitles
from salin.error import ExtractorError, LanguageParseError, VideoUnavailableError
from salin.languages import parse_languages
from salin.shared.models import LangCode, LanguageMatch, SubtitleSourcePolicy, UrlStr


def test_parse_languages_success():
    specs = parse_languages("en")
    assert len(specs) == 1
    assert specs[0].requested == "en"
    assert specs[0].variants == ()

    specs = parse_languages(["en", "es"])
    assert len(specs) == 2
    assert specs[0].requested == "en"
    assert specs[1].requested == "es"

    specs = parse_languages({"en": ["en-US", "en-GB"], "de": "de"})
    assert len(specs) == 2
    assert specs[0].requested == "en"
    assert specs[0].variants == ("en-US", "en-GB")
    assert specs[1].requested == "de"
    assert specs[1].variants == ("de",)


def test_parse_languages_error():
    with pytest.raises(LanguageParseError):
        parse_languages("")

    with pytest.raises(LanguageParseError):
        parse_languages([])

    with pytest.raises(LanguageParseError):
        # Variant must match requested prefix
        parse_languages({"en": ["es-ES"]})

    with pytest.raises(LanguageParseError):
        # Invalid input type
        parse_languages(123)  # type: ignore


def test_resolve_subtitles_exact():
    requested = parse_languages("en")
    manual = frozenset(map(LangCode, ["en", "es"]))
    auto = frozenset(map(LangCode, ["de"]))

    resolved = resolve_subtitles(
        requested,
        manual_langs=manual,
        auto_langs=auto,
        language_match=LanguageMatch.EXACT,
        source_policy=SubtitleSourcePolicy.MANUAL_THEN_AUTO,
    )
    assert len(resolved) == 1
    assert resolved[0].requested == "en"
    assert resolved[0].resolved == "en"
    assert resolved[0].source == "manual"
    assert resolved[0].is_resolved is True


def test_resolve_subtitles_regional():
    requested = parse_languages("en")
    manual = frozenset(map(LangCode, ["en-US"]))
    auto = frozenset()

    # Regional match should find en-US for en
    resolved = resolve_subtitles(
        requested,
        manual_langs=manual,
        auto_langs=auto,
        language_match=LanguageMatch.REGIONAL,
        source_policy=SubtitleSourcePolicy.MANUAL_THEN_AUTO,
    )
    assert len(resolved) == 1
    assert resolved[0].requested == "en"
    assert resolved[0].resolved == "en-US"
    assert resolved[0].source == "manual"
    assert resolved[0].is_resolved is True


def test_resolve_subtitles_policies():
    requested = parse_languages("en")
    manual = frozenset()
    auto = frozenset(map(LangCode, ["en"]))

    # Manual only shouldn't find auto en
    resolved_manual_only = resolve_subtitles(
        requested,
        manual_langs=manual,
        auto_langs=auto,
        language_match=LanguageMatch.EXACT,
        source_policy=SubtitleSourcePolicy.MANUAL_ONLY,
    )
    assert len(resolved_manual_only) == 1
    assert resolved_manual_only[0].requested == "en"
    assert resolved_manual_only[0].resolved is None
    assert resolved_manual_only[0].source is None
    assert resolved_manual_only[0].is_resolved is False

    # Auto only should find auto en
    resolved_auto_only = resolve_subtitles(
        requested,
        manual_langs=manual,
        auto_langs=auto,
        language_match=LanguageMatch.EXACT,
        source_policy=SubtitleSourcePolicy.AUTO_ONLY,
    )
    assert len(resolved_auto_only) == 1
    assert resolved_auto_only[0].resolved == "en"
    assert resolved_auto_only[0].source == "auto"
    assert resolved_auto_only[0].is_resolved is True


def test_resolve_subtitles_unresolved():
    requested = parse_languages(["en", "de"])
    manual = frozenset(map(LangCode, ["en"]))
    auto = frozenset()

    resolved = resolve_subtitles(
        requested,
        manual_langs=manual,
        auto_langs=auto,
        language_match=LanguageMatch.EXACT,
        source_policy=SubtitleSourcePolicy.MANUAL_ONLY,
    )
    assert len(resolved) == 2
    assert resolved[0].requested == "en"
    assert resolved[0].resolved == "en"
    assert resolved[0].is_resolved is True

    assert resolved[1].requested == "de"
    assert resolved[1].resolved is None
    assert resolved[1].is_resolved is False


def test_extract_info_error_handling(monkeypatch):
    def mock_extract_info(*args, **kwargs):
        raise yt_dlp.utils.DownloadError("This video is unavailable in your country")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    with pytest.raises(VideoUnavailableError) as excinfo:
        extract_info(UrlStr("https://www.youtube.com/watch?v=unavailable"))
    assert "Video is unavailable" in str(excinfo.value)


def test_extract_info_generic_error(monkeypatch):
    def mock_extract_info(*args, **kwargs):
        raise yt_dlp.utils.DownloadError("Some random network error")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    with pytest.raises(ExtractorError) as excinfo:
        extract_info(UrlStr("https://www.youtube.com/watch?v=network_fail"))
    assert "Failed to extract video info" in str(excinfo.value)


def test_client_optional_languages_error():
    client = Salin()
    with pytest.raises(LanguageParseError) as excinfo:
        client.resolve("https://www.youtube.com/watch?v=abc123")
    assert "No languages specified" in str(excinfo.value)

    with pytest.raises(LanguageParseError) as excinfo:
        client.download("https://www.youtube.com/watch?v=abc123")
    assert "No languages specified" in str(excinfo.value)


def test_client_string_enum_parameters():
    client = Salin(
        languages="en",
        language_match="exact",
        source_policy="manual_only",
    )
    assert client.language_match == LanguageMatch.EXACT
    assert client.source_policy == SubtitleSourcePolicy.MANUAL_ONLY


def test_client_sleep_defaults_do_not_add_delay():
    client = Salin(languages="en")

    assert client.sleep_interval_subtitles == 0
    assert client.sleep_interval_requests == 1

    assert (
        Salin(languages="en", sleep_interval_subtitles=2).sleep_interval_subtitles == 2
    )
    assert (
        Salin(languages="en", sleep_interval_subtitles=0).sleep_interval_subtitles == 0
    )
