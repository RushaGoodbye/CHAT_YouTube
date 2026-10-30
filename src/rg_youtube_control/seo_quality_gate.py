"""Small, dependency-free editorial quality gate for Ukrainian YouTube SEO.

This module scores structure and obvious language errors only. It deliberately
does not claim to prove facts from a transcript, or approve publication.
"""
from __future__ import annotations

import re
from typing import Any

_RUSSIAN_WORDS = re.compile(
    r"(?<![\w])(?:россия|россии|россияне|увольнение|коррупция|"
    r"говорят|почему|война|путин|мобилизация|санкции|"
    r"вопросы|ответы|жизнь|мнение|зарплаты|пенсии)(?![\w])",
    re.IGNORECASE,
)
_NON_UKRAINIAN_LETTERS = re.compile(r"[ыэъё]", re.IGNORECASE)


def language_error(value: str) -> bool:
    """Flag strong Russian-language signals without rejecting Ukrainian proper names."""
    text = str(value or "")
    return bool(_NON_UKRAINIAN_LETTERS.search(text) or _RUSSIAN_WORDS.search(text))


def inspect_package(package: dict[str, Any]) -> dict[str, Any]:
    """Return reproducible, field-level defects, with no content leaked to logs."""
    problems: dict[str, list[str]] = {}
    title = str(package.get("title") or "").strip()
    variants = [str(x).strip() for x in (package.get("title_variants") or [])]
    description = str(package.get("description") or "").strip()
    tags = [str(x).strip() for x in (package.get("tags") or [])]

    def add(field: str, reason: str) -> None:
        problems.setdefault(field, []).append(reason)

    if not title:
        add("title", "MISSING")
    elif len(title) > 100:
        add("title", "OVER_100_CHARS")
    if language_error(title):
        add("title", "NON_UKRAINIAN")
    if len(variants) != 3:
        add("title_variants", "COUNT_NOT_THREE")
    if len(set(x.casefold() for x in variants)) != len(variants):
        add("title_variants", "DUPLICATE")
    for value in variants:
        if len(value) > 100:
            add("title_variants", "OVER_100_CHARS")
        if language_error(value):
            add("title_variants", "NON_UKRAINIAN")
    if len(description) < 260:
        add("description", "SHORT")
    if language_error(description):
        add("description", "NON_UKRAINIAN")
    if len(tags) < 8:
        add("tags", "FEWER_THAN_EIGHT")
    if any(language_error(x) for x in tags):
        add("tags", "NON_UKRAINIAN")

    return {
        "format_pass": not problems,
        "editorial_review_required": True,
        "problems": problems,
        "counts": {"variants": len(variants), "tags": len(tags)},
    }


def sanitize_review_variants(
    title: str,
    variants: list[str],
    source_topic_suggestions: list[str],
) -> tuple[list[str], bool]:
    """Remove obvious Russian A/B drafts; restore only source-topic alternatives.

    Never translate unsupported claims or create artificial duplicates.
    The caller must mark a changed result as review-only.
    """
    original = [str(item).strip() for item in variants if str(item).strip()]
    accepted: list[str] = []
    used = {str(title or "").strip().casefold()}
    for item in [*original, *source_topic_suggestions]:
        candidate = str(item).strip()
        key = candidate.casefold()
        if not candidate or len(candidate) > 100 or key in used or language_error(candidate):
            continue
        # Source-topic suggestions may fill missing slots, but cannot validate facts.
        used.add(key)
        accepted.append(candidate)
        if len(accepted) >= 3:
            break
    return accepted, accepted != original[:3]
