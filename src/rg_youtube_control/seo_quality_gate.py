"""Small, dependency-free editorial quality gate for Ukrainian YouTube SEO.

This module scores structure and obvious language errors only. It deliberately
does not claim to prove facts from a transcript, or approve publication.
"""
from __future__ import annotations

import re
from typing import Any

_RUSSIAN_WORDS = re.compile(
    r"(?<![\w])(?:россия|россии|россияне|увольнение|коррупция|"
    r"говорят|почему|война|путин|мобилизация|санкции|диалог|доносов|гордость|контрактники|"
    r"вопросы|ответы|жизнь|мнение|зарплаты|пенсии|россией|украина|украины|"
    r"поддерживает|войну|голосовать|путина|россиянина|после|мобилизации|"
    r"реакция|дети|или|алкоголь|что|кто|было|стало|зачем|против)(?![\w])",
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
    variant_keys = [x.casefold() for x in variants]
    if len(set(variant_keys)) != len(variant_keys) or title.casefold() in variant_keys:
        add("title_variants", "DUPLICATE")
    if any(not x for x in variants):
        add("title_variants", "EMPTY")
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
    tag_keys = [re.sub(r"\s+", " ", x).strip().casefold() for x in tags]
    if any(not x for x in tags):
        add("tags", "EMPTY")
    if len(set(tag_keys)) != len(tag_keys):
        add("tags", "DUPLICATE")
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


def inspect_editorial_targets(package: dict[str, Any]) -> dict[str, Any]:
    """Stricter editorial QA; never grants publishing approval.

    A syntactically valid SEO package may still fail editorial requirements.
    All claims and ranking of topics require human source checking.
    """
    result = inspect_package(package)
    issues = dict(result["problems"])
    description = str(package.get("description") or "").strip()
    if 260 <= len(description) < 400:
        issues.setdefault("description", []).append("DESCRIPTION_UNDER_EDITORIAL_TARGET")
    title = str(package.get("title") or "").strip()
    weak_title = re.search(
        r"(?i)^(?:співрозмовник|учасники|міркування|питання про|бажання|розмова про|аналіз)\b",
        title,
    )
    if weak_title:
        issues.setdefault("title", []).append("GENERIC_TITLE_REVIEW")
    return {"editorial_gate_pass": not issues,
            "editorial_approved": False, "publication_allowed": False,
            "issues": issues}
