"""Parse and validate language request specifications."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from salin.error import LanguageParseError
from salin.shared.models import (
    LangCodeRequested,
    LangCodeResolved,
    LanguagesInput,
    LanguageSpec,
)


def _variant_matches_requested(requested: str, variant: str) -> bool:
    return variant == requested or variant.startswith(f"{requested}-")


def _validate_requested(code: str) -> LangCodeRequested:
    if len(code) < 2:
        raise LanguageParseError(
            f"invalid language code: {code!r}. "
            "Use languages='en' or languages={'en': ['en-US']}."
        )
    return LangCodeRequested(code)


def _variants_from_value(
    requested: LangCodeRequested,
    value: str | Iterable[str] | None,
) -> tuple[LangCodeResolved, ...]:
    if value is None:
        return ()

    values = (value,) if isinstance(value, str) else tuple(value)
    resolved: list[LangCodeResolved] = []
    seen: set[str] = set()

    for item in values:
        variant = str(item)
        if variant in seen:
            continue
        if not _variant_matches_requested(requested, variant):
            raise LanguageParseError(
                f"variant {variant!r} is not valid for requested language "
                f"{requested!r}; expected {requested!r} or a regional code "
                f"like {requested}-US"
            )
        seen.add(variant)
        resolved.append(LangCodeResolved(variant))

    return tuple(resolved)


def _specs_from_mapping(
    mapping: dict[str, Iterable[str]],
) -> list[LanguageSpec]:
    specs: list[LanguageSpec] = []
    for requested_raw, variants_raw in mapping.items():
        requested = _validate_requested(str(requested_raw))
        specs.append(
            LanguageSpec(
                requested=requested,
                variants=_variants_from_value(requested, variants_raw),
            )
        )
    return specs


def parse_languages(languages: LanguagesInput | None) -> tuple[LanguageSpec, ...]:
    """
    Normalize language input into validated LanguageSpec values.

    Accepted forms:
      - "en"
      - ["en", "de"]
      - {"en": ["en-orig", "en-US"], "de": ["de-DE", "de"]}
      - [{"en": ["en-orig", "en-US"]}, {"de": ["de-DE"]}]
    """
    if languages is None:
        raise LanguageParseError("""'languages' must be set in either the Salin client constructor, 'download', or 'download_many'.
Accepted forms:
    - "en"
    - ["en", "de"]
    - {"en": ["en-orig", "en-US"], "de": ["de-DE", "de"]}
    - [{"en": ["en-orig", "en-US"]}, {"de": ["de-DE"]}]
        """)

    if isinstance(languages, str):
        requested = _validate_requested(languages)
        return (LanguageSpec(requested=requested),)

    if isinstance(languages, dict):
        mapping = cast(dict[str, Iterable[str]], languages)

        specs = _specs_from_mapping(mapping)
        if not specs:
            raise LanguageParseError("languages cannot be empty")
        return tuple(specs)

    if not isinstance(languages, Iterable):
        raise LanguageParseError(
            "languages must be a string, mapping, or sequence of strings/mappings"
        )

    specs: list[LanguageSpec] = []
    for item in languages:
        if isinstance(item, str):
            specs.append(LanguageSpec(requested=_validate_requested(item)))
        elif isinstance(item, dict):
            if len(item) != 1:
                raise LanguageParseError("each language dict must have exactly one key")
            specs.extend(_specs_from_mapping(item))
        else:
            raise LanguageParseError(
                "languages must be a string, mapping, or sequence of strings/mappings"
            )

    if not specs:
        raise LanguageParseError("languages cannot be empty")

    return tuple(specs)
