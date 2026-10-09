"""Conservative local SEO quality report; never publishes to YouTube."""
from __future__ import annotations

from .dialogue_seo import ab_title_issues, preserve_outline_topics


def review_seo_package(
    *,
    title: str,
    description: str,
    variants: list[str],
    evidence_report: dict | None,
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

    report = evidence_report or {}
    blocks = report.get("blocks") or []
    if not blocks:
        issues.append("Немає звіту про повноту аналізу відео.")
        return issues
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
    # Exact quote matching is intentionally conservative: paraphrases need review.
    # Do not auto-publish a summary that silently loses transcript evidence.
    missing_quotes = []
    for block in blocks:
        for item in block.get("topics") or []:
            quote = str(item.get("evidence") or "").strip()
            if quote and quote.casefold() not in description.casefold():
                missing_quotes.append(quote)
    if missing_quotes:
        issues.append(
            "Цитати з аналізу не збережені дослівно в описі; "
            "перевірте, чи не втрачено ключові моменти: "
            + "; ".join(dict.fromkeys(missing_quotes))[:450]
        )
    return list(dict.fromkeys(issues))
