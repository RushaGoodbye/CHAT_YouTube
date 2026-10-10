"""Conservative local SEO quality report; never publishes to YouTube."""
from __future__ import annotations

import re

from .dialogue_seo import ab_title_issues, preserve_outline_topics


def review_seo_package(
    *,
    title: str,
    description: str,
    variants: list[str],
    evidence_report: dict | None,
    original_description: str | None = None,
    original_tags: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[str]:
    """Return actionable warnings that must prevent READY status.

    This is a review gate, not a guarantee that every claim is true.
    """
    issues: list[str] = []
    main_title = str(title or "").strip()
    if not main_title or not (20 <= len(main_title) <= 100):
        issues.append("Основна назва має містити 20-100 символів.")
    issues.extend(ab_title_issues(variants, evidence_report))
    if any(str(v).strip().casefold() == main_title.casefold() for v in variants):
        issues.append("A/B-альтернативи повторюють основну назву.")

    if original_description is not None:
        # Retain original URL destinations when compressing existing descriptions.
        url_pattern = r"https?://[^\s<>\"']+"
        old_urls = {url.rstrip(".,;!)") for url in re.findall(url_pattern, original_description)}
        new_urls = {url.rstrip(".,;!)") for url in re.findall(url_pattern, description)}
        if old_urls - new_urls:
            issues.append("Новий опис втратив посилання з оригіналу; перевірте збереження URL.")
    # Replacing a populated source tag set with no tags is a loss, not
    # SEO optimization. Relevance-based tag replacement remains allowed.
    if original_tags and tags is not None and not [
        str(tag).strip() for tag in tags if str(tag).strip()
    ]:
        issues.append("SEO-пакет втратив усі теги з оригіналу.")
    report = evidence_report or {}
    blocks = report.get("blocks") or []
    if not blocks:
        issues.append("Немає звіту про повноту аналізу відео.")
        return issues
    # Only the timeline analyzer can attest complete coverage. A model's
    # "needs_review: false" flag is NOT proof all source captions were covered.
    total = report.get("blocks_total")
    analyzed = report.get("blocks_analyzed")
    covered_rows = report.get("rows_covered")
    verified_count = report.get("blocks_with_evidence")
    missing = report.get("unverified_blocks")
    if (
        type(total) is not int or type(analyzed) is not int
        or total <= 0 or analyzed != total or len(blocks) != total
        or type(covered_rows) is not int or covered_rows <= 0
    ):
        issues.append(
            "Неповне покриття транскрипту: кількість часових фрагментів "
            "або охоплених реплік не підтверджена."
        )
    source_hash = report.get("source_text_sha256")
    covered_hash = report.get("covered_text_sha256")
    source_chars = report.get("source_text_chars")
    covered_chars = report.get("covered_text_chars")
    source_rows = report.get("source_rows_with_text")
    if (
        report.get("source_integrity_verified") is not True
        or not isinstance(source_hash, str) or len(source_hash) != 64
        or source_hash != covered_hash
        or type(source_chars) is not int or source_chars <= 0
        or type(covered_chars) is not int or source_chars != covered_chars
        or type(source_rows) is not int or source_rows <= 0
    ):
        issues.append(
            "Цілісність транскрипту не підтверджена: частина реплік "
            "могла загубитися під час аналізу."
        )
    if (
        type(verified_count) is not int
        or verified_count != sum(bool(block.get("topics")) for block in blocks)
        or verified_count != len(blocks)
        or not isinstance(missing, list)
        or missing
    ):
        issues.append(
            "Не всі часові фрагменти мають перевірені теми; "
            "пакет потребує ручного перегляду."
        )
    for block in blocks:
        for item in block.get("topics") or []:
            if not isinstance(item, dict) or not str(item.get("evidence") or "").strip():
                issues.append(
                    "Частина тем не має доказової цитати з транскрипту."
                )
                break
    if report.get("needs_review"):
        issues.append("Не всі часові фрагменти отримали перевірені теми.")
    if any(not (block.get("topics") or []) for block in blocks):
        issues.append("Деякі часові фрагменти залишилися без підтвердженої теми.")
    _, missing = preserve_outline_topics(description, report)
    if missing:
        issues.append("В описі не вмістилися теми: " + "; ".join(missing[:8]))
    # Added topics may be appended later, but this is a signal to review
    # the whole description with original evidence, not automatic approval.
    missing_in_text = []
    for block in blocks:
        for item in block.get("topics") or []:
            topic = str(item.get("topic") or "").strip()
            if topic and topic.casefold() not in description.casefold():
                missing_in_text.append(topic)
    if missing_in_text:
        issues.append(
            "Частина тем відсутня у згенерованому описі: "
            + "; ".join(dict.fromkeys(missing_in_text))[:500]
        )
    # A concise description need not reproduce every quote verbatim.
    # Keep at least one concrete, source-backed quotation when evidence exists;
    # otherwise flag for editorial review rather than claiming the rewrite is safe.
    evidence_quotes = list(dict.fromkeys(
        str(item.get("evidence") or "").strip()
        for block in blocks
        for item in block.get("topics") or []
        if str(item.get("evidence") or "").strip()
    ))
    if evidence_quotes and not any(
        quote.casefold() in description.casefold() for quote in evidence_quotes
    ):
        issues.append(
            "В описі немає жодної дослівної цитати з підтверджених "
            "фрагментів; перевірте, чи збережено сильний момент діалогу."
        )
    return list(dict.fromkeys(issues))
