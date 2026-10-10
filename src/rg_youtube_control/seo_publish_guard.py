"""Fail-closed publication gate for saved/legacy RG SEO content packages.

A stored status='ready' is not a semantic-quality certificate. Before ever
offering videos.update, revalidate actual metadata, source URLs and the
complete local evidence report. No network access or model calls.
"""
from __future__ import annotations

import re

from .optimization import (
    safe_description_needs_content_package,
    validate_content_package,
)
from .seo_quality_gate import review_seo_package


TEMPLATE_DESCRIPTION_PHRASES = (
    "обговорюємо тему, зазначену в назві",
    "фіксуємо реальні діалоги без вигадування контексту",
    "у цьому відео обговорюємо тему",
    "обсуждаем тему, указанную в названии",
    "тема указана в названии",
    "дивіться відео до кінця, щоб дізнатися",
)
GENERIC_CHAPTER_LABELS = {
    "вступ", "початок", "наступний блок", "основна частина",
    "фінальна частина", "завершення", "введение",
    "следующий блок", "финальная часть", "основная часть",
}


def ready_package_blockers(
    *,
    title: str,
    description: str,
    chapters: str,
    tags: list[str],
    variants: list[str],
    scheduled: bool = False,
    evidence_report: dict | None = None,
    original_description: str = "",
    original_tags: list[str] | None = None,
) -> list[str]:
    """Return reasons a content package must stay in review, never auto-post."""
    errors: list[str] = []
    clean_title = " ".join(str(title or "").split())
    clean_description = str(description or "").strip()
    check = validate_content_package(
        clean_title, clean_description, str(chapters or ""), tags, variants,
        chapters_optional=scheduled,
    )
    errors.extend(str(issue) for issue in check.errors)

    lower = " ".join(clean_description.casefold().split())
    if any(phrase in lower for phrase in TEMPLATE_DESCRIPTION_PHRASES):
        errors.append("Шаблонний опис без конкретного змісту розмови.")
    if safe_description_needs_content_package(clean_description, clean_title):
        errors.append("В описі недостатньо конкретного змісту відео.")

    if not scheduled:
        for line in (chapters or "").splitlines():
            match = re.match(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s+(.+)$", line)
            if match and match.group(1).strip().casefold() in GENERIC_CHAPTER_LABELS:
                errors.append("Непідтверджені шаблонні назви розділів.")
                break
        if not str(original_description or "").strip():
            errors.append("Немає підтвердженого оригінального опису відео.")
        if not evidence_report:
            errors.append("Немає перевіреного аналізу транскрипту відео.")
        else:
            errors.extend(review_seo_package(
                title=clean_title,
                description=clean_description,
                variants=variants,
                evidence_report=evidence_report,
                original_description=original_description,
                original_tags=original_tags or [],
                tags=tags,
            ))
    return list(dict.fromkeys(errors))
