from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .config import DONATE_URL, PROJECT_LINKS_URL
from .metadata_audit import HASHTAG_RE, normalize_links

@dataclass(frozen=True)
class SafeFix:
    before: str
    after: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class PackageCheck:
    ready: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

SAFE_LINK_ISSUES = frozenset({
    "old_links",
    "missing_project_link",
    "missing_donate_link",
    "too_many_hashtags",
})

HASHTAG_ONLY_LINE_RE = re.compile(
    r"^\s*(?:#[\wА-Яа-яІіЇїЄєҐґ]+\s*)+$",
    re.UNICODE,
)


def has_safe_link_issue(issues: list[str] | tuple[str, ...]) -> bool:
    return bool(SAFE_LINK_ISSUES.intersection(issues))


def _trim_hashtag_only_lines(value: str, limit: int = 3) -> tuple[str, bool]:
    lines = value.splitlines()
    kept_elsewhere = 0
    changed = False
    output: list[str] = []

    for line in lines:
        tokens = HASHTAG_RE.findall(line)
        if not HASHTAG_ONLY_LINE_RE.fullmatch(line):
            kept_elsewhere += len(tokens)
            output.append(line)
            continue

        room = max(0, limit - kept_elsewhere)
        kept = tokens[:room]
        kept_elsewhere += len(kept)
        if len(kept) != len(tokens):
            changed = True
        if kept:
            output.append(" ".join(kept))
        elif line.strip():
            changed = True

    result = "\n".join(output)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result, changed


def safe_description_fix(description: str) -> SafeFix:
    before = description or ""
    after = normalize_links(before)
    changes: list[str] = []

    if after != before:
        changes.append("замінено старі посилання")

    after, hashtags_trimmed = _trim_hashtag_only_lines(after, limit=3)
    if hashtags_trimmed:
        changes.append("залишено не більше 3 хештегів")

    missing_project = PROJECT_LINKS_URL not in after
    missing_donate = DONATE_URL not in after

    additions: list[str] = []
    if missing_project:
        additions.append(
            "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n"
            f"{PROJECT_LINKS_URL}"
        )
        changes.append("додано посилання проєкту")
    if missing_donate:
        additions.append(
            "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:\n"
            f"{DONATE_URL}"
        )
        changes.append("додано посилання на донат")

    if additions:
        after = after.rstrip()
        if after:
            after += "\n\n"
        after += "\n\n".join(additions)

    return SafeFix(before=before, after=after, changes=tuple(changes))

def archive_potential_score(
    *,
    lifetime_views: int,
    analytics_views: int,
    impressions: int,
    ctr_percent: float,
    median_ctr_percent: float,
    issues: list[str] | tuple[str, ...],
) -> int:
    """Heuristic opportunity score for archive work, 0..100.

    It intentionally rewards videos that already have audience/reach and
    still have fixable metadata weaknesses. Low CTR only contributes when
    there are enough impressions and a channel-relative median is known.
    """
    score = 0.0
    recent_views = max(0, int(analytics_views or 0))
    lifetime = max(0, int(lifetime_views or 0))
    impressions = max(0, int(impressions or 0))
    ctr = max(0.0, float(ctr_percent or 0.0))
    median_ctr = max(0.0, float(median_ctr_percent or 0.0))

    if recent_views:
        score += min(25.0, math.log10(recent_views + 1) * 5.0)
    elif lifetime:
        score += min(20.0, math.log10(lifetime + 1) * 4.0)

    if impressions >= 1000:
        score += min(35.0, math.log10(impressions + 1) * 7.0)
        if median_ctr > 0 and ctr < median_ctr:
            relative_gap = (median_ctr - ctr) / median_ctr
            score += min(25.0, relative_gap * 25.0)

    issue_weights = {
        "no_chapters": 8.0,
        "thin_description": 6.0,
        "no_tags": 4.0,
        "too_many_hashtags": 2.0,
        "old_links": 1.0,
        "missing_project_link": 1.0,
        "missing_donate_link": 1.0,
    }
    for issue in set(issues):
        score += issue_weights.get(issue, 0.0)

    return max(0, min(100, int(round(score))))


def priority_label(
    audit_score: int,
    privacy_status: str | None,
    scheduled_publish_at: str | None,
    issues: list[str] | tuple[str, ...],
) -> tuple[int, str]:
    issue_set = set(issues)
    if scheduled_publish_at:
        return 1000, "ЗАПЛАНОВАНО"
    if "old_links" in issue_set:
        return 800, "ВИСОКИЙ"
    if "missing_project_link" in issue_set or "missing_donate_link" in issue_set:
        return 700, "ВИСОКИЙ"
    if audit_score < 50:
        return 500, "СЕРЕДНІЙ"
    if audit_score < 100:
        return 300, "НИЗЬКИЙ"
    return 0, "ГОТОВО"


CHAPTER_LINE_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s+(.+?)\s*$"
)

def _chapter_seconds(match: re.Match[str]) -> int:
    first = int(match.group(1))
    second = int(match.group(2))
    third = match.group(3)
    if third is None:
        return first * 60 + second
    return first * 3600 + second * 60 + int(third)

def validate_chapters(chapters: str) -> tuple[bool, str]:
    value = chapters.strip()
    if not value:
        return True, ""
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 3:
        return False, "Для ручних розділів потрібно щонайменше 3 таймкоди."
    points: list[int] = []
    for line in lines:
        match = CHAPTER_LINE_RE.match(line)
        if not match:
            return False, f"Некоректний формат розділу: {line}"
        second = int(match.group(2))
        third = match.group(3)
        if second > 59 or (third is not None and int(third) > 59):
            return False, f"Некоректне значення часу: {line}"
        points.append(_chapter_seconds(match))
    if points[0] != 0:
        return False, "Перший розділ має починатися з 00:00."
    if points != sorted(points) or len(set(points)) != len(points):
        return False, "Таймкоди мають іти строго за зростанням."
    for left, right in zip(points, points[1:]):
        if right - left < 10:
            return False, "Кожен розділ має тривати щонайменше 10 секунд."
    return True, ""

def extract_chapters_from_description(
    description: str,
) -> tuple[str, str]:
    lines = (description or "").splitlines()
    chapter_lines = [
        line.strip()
        for line in lines
        if CHAPTER_LINE_RE.match(line.strip())
    ]
    if len(chapter_lines) < 3:
        return (description or "").strip(), ""

    chapters = "\n".join(chapter_lines)
    ok, _message = validate_chapters(chapters)
    if not ok:
        return (description or "").strip(), ""

    chapter_set = set(chapter_lines)
    body_lines = [
        line
        for line in lines
        if line.strip() not in chapter_set
    ]
    body = "\n".join(body_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body, chapters


def validate_content_package(
    title: str,
    description: str,
    chapters: str,
    tags: list[str] | None,
    title_variants: list[str] | None = None,
) -> PackageCheck:
    errors: list[str] = []
    warnings: list[str] = []

    clean_title = (title or "").strip()
    clean_description = (description or "").strip()
    clean_tags = [str(item).strip() for item in (tags or []) if str(item).strip()]
    clean_variants = [
        str(item).strip()
        for item in (title_variants or [])
        if str(item).strip()
    ]

    if not clean_title:
        errors.append("Назва порожня.")
    elif len(clean_title) > 100:
        errors.append(
            f"Назва має {len(clean_title)} символів. YouTube дозволяє не більше 100."
        )

    if not clean_description:
        errors.append("Опис порожній.")
    elif len(clean_description) > 5000:
        errors.append(
            f"Опис має {len(clean_description)} символів. YouTube дозволяє не більше 5000."
        )
    elif len(clean_description) < 250:
        warnings.append("Опис коротший за 250 символів.")

    if PROJECT_LINKS_URL not in clean_description:
        warnings.append("В описі немає актуального посилання проєкту.")
    if DONATE_URL not in clean_description:
        warnings.append("В описі немає актуального посилання на донат.")

    chapter_ok, chapter_message = validate_chapters(chapters)
    if not chapter_ok:
        errors.append(chapter_message)
    elif not chapters.strip():
        warnings.append("Розділи не заповнені.")

    if not clean_tags:
        warnings.append("Теги не заповнені.")
    else:
        normalized_tags = [item.casefold() for item in clean_tags]
        if len(normalized_tags) != len(set(normalized_tags)):
            warnings.append("У тегах є дублікати.")
        tag_chars = len(", ".join(clean_tags))
        if tag_chars > 500:
            errors.append(
                f"Теги займають приблизно {tag_chars} символів. "
                "Потрібно вкластися у 500."
            )

    hashtags = re.findall(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", clean_description)
    if len(hashtags) > 3:
        warnings.append("В описі більше 3 хештегів.")

    if len(clean_variants) < 3:
        warnings.append("Для A/B перевірки бажано мати 3 варіанти назви.")
    if len({item.casefold() for item in clean_variants}) != len(clean_variants):
        warnings.append("Серед A/B варіантів є дублікати.")
    for index, variant in enumerate(clean_variants, start=1):
        if len(variant) > 100:
            errors.append(
                f"A/B варіант {index} має {len(variant)} символів. "
                "Потрібно не більше 100."
            )

    return PackageCheck(
        ready=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def compose_description(description: str, chapters: str) -> str:
    body = (description or "").strip()
    chapter_block = chapters.strip()
    if not chapter_block:
        return body

    ok, message = validate_chapters(chapter_block)
    if not ok:
        raise ValueError(message)

    service_markers = (
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:",
        "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:",
    )
    split_at = None
    for marker in service_markers:
        pos = body.find(marker)
        if pos >= 0:
            split_at = pos if split_at is None else min(split_at, pos)

    if split_at is None:
        return f"{body}\n\n{chapter_block}".strip()

    main = body[:split_at].rstrip()
    service = body[split_at:].lstrip()
    return f"{main}\n\n{chapter_block}\n\n{service}".strip()