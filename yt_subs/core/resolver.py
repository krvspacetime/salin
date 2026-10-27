"""
core/resolver.py

Language resolution: maps requested lang codes to the best available
yt-dlp track code, preferring manual subtitles over auto-generated.
"""

from __future__ import annotations

import logging

from yt_subs.languages import LanguageSpec
from yt_subs.shared.models import (
    LangCode,
    LangCodeRequested,
    LangCodeResolved,
    LanguageMatch,
    ResolvedSubtitle,
    SubtitleAvailability,
    SubtitleSource,
    SubtitleSourcePolicy,
)

log = logging.getLogger(__name__)


def regional_candidates_auto(
    requested: LangCodeRequested,
    *,
    manual_langs: frozenset[LangCode],
    auto_langs: frozenset[LangCode],
) -> tuple[LangCodeResolved, ...]:
    """Pick the first available exact or regional match with no custom order."""
    all_langs = manual_langs | auto_langs
    result: list[LangCodeResolved] = []
    seen: set[LangCodeResolved] = set()

    def add(candidate: LangCode | str) -> None:
        resolved = LangCodeResolved(str(candidate))
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)

    if requested in all_langs:
        add(requested)

    for candidate in sorted(all_langs):
        if str(candidate).startswith(f"{requested}-") and candidate != requested:
            add(candidate)

    return tuple(result)


def _merge_candidates(
    preferred: tuple[LangCodeResolved, ...],
    *,
    requested: LangCodeRequested,
    manual_langs: frozenset[LangCode],
    auto_langs: frozenset[LangCode],
) -> tuple[LangCodeResolved, ...]:
    """Try preferred variants first, then fall back to auto regional discovery."""
    result: list[LangCodeResolved] = []
    seen: set[LangCodeResolved] = set()

    for candidate in preferred:
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)

    for candidate in regional_candidates_auto(
        requested,
        manual_langs=manual_langs,
        auto_langs=auto_langs,
    ):
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)

    return tuple(result)


def candidates_for(
    spec: LanguageSpec,
    *,
    manual_langs: frozenset[LangCode],
    auto_langs: frozenset[LangCode],
    language_match: LanguageMatch,
) -> tuple[LangCodeResolved, ...]:
    if language_match == LanguageMatch.EXACT:
        return (LangCodeResolved(spec.requested),)

    if spec.has_variants:
        return _merge_candidates(
            spec.variants,
            requested=spec.requested,
            manual_langs=manual_langs,
            auto_langs=auto_langs,
        )

    return regional_candidates_auto(
        spec.requested,
        manual_langs=manual_langs,
        auto_langs=auto_langs,
    )


def resolve_subtitles(
    requested: tuple[LanguageSpec, ...],
    manual_langs: frozenset[LangCode],
    auto_langs: frozenset[LangCode],
    language_match: LanguageMatch,
    source_policy: SubtitleSourcePolicy,
) -> tuple[ResolvedSubtitle, ...]:
    resolved: list[ResolvedSubtitle] = []

    def find_in(
        candidates: tuple[LangCodeResolved, ...], pool: frozenset[LangCode]
    ) -> LangCodeResolved | None:
        return next((c for c in candidates if c in pool), None)

    for spec in requested:
        candidates = candidates_for(
            spec,
            manual_langs=manual_langs,
            auto_langs=auto_langs,
            language_match=language_match,
        )

        match source_policy:
            case SubtitleSourcePolicy.MANUAL_ONLY:
                sources = [(manual_langs, SubtitleSource.MANUAL)]
            case SubtitleSourcePolicy.AUTO_ONLY:
                sources = [(auto_langs, SubtitleSource.AUTO)]
            case SubtitleSourcePolicy.MANUAL_THEN_AUTO:
                sources = [
                    (manual_langs, SubtitleSource.MANUAL),
                    (auto_langs, SubtitleSource.AUTO),
                ]
            case SubtitleSourcePolicy.AUTO_THEN_MANUAL:
                sources = [
                    (auto_langs, SubtitleSource.AUTO),
                    (manual_langs, SubtitleSource.MANUAL),
                ]

        match = next(
            (
                ResolvedSubtitle(
                    requested=spec.requested,
                    resolved=LangCodeResolved(found),
                    source=source,
                )
                for pool, source in sources
                if (found := find_in(candidates, pool))
            ),
            None,
        )

        if match:
            resolved.append(match)
        else:
            if candidates:
                tried_str = ", ".join(f"'{c}'" for c in candidates)
            else:
                tried_str = "none"
            log.warning(
                "'%s' not available (tried: %s, policy: %s, match: %s)",
                spec.requested,
                tried_str,
                source_policy,
                language_match,
            )
            resolved.append(
                ResolvedSubtitle(
                    requested=spec.requested,
                    resolved=None,
                    source=None,
                )
            )

    return tuple(resolved)


def resolve_availability(
    availability: SubtitleAvailability,
    *,
    languages: tuple[LanguageSpec, ...],
    language_match: LanguageMatch,
    source_policy: SubtitleSourcePolicy,
) -> tuple[ResolvedSubtitle, ...]:
    return resolve_subtitles(
        languages,
        availability.manual,
        availability.auto,
        language_match,
        source_policy,
    )
