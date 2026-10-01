from __future__ import annotations

import re
from dataclasses import dataclass

from .config import DONATE_URL, PROJECT_LINKS_URL
from .metadata_audit import normalize_links

@dataclass(frozen=True)
class SafeFix:
    before: str
    after: str
    changes: tuple[str, ...]

SAFE_LINK_ISSUES = frozenset({
    "old_links",
    "missing_project_link",
    "missing_donate_link",
})


def has_safe_link_issue(issues: list[str] | tuple[str, ...]) -> bool:
    return bool(SAFE_LINK_ISSUES.intersection(issues))


def safe_description_fix(description: str) -> SafeFix:
    before = description or ""
    after = normalize_links(before)
    changes: list[str] = []

    if after != before:
        changes.append("замінено старі посилання")

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
        return False, "Для ручных глав нужно минимум 3 таймкода."
    points: list[int] = []
    for line in lines:
        match = CHAPTER_LINE_RE.match(line)
        if not match:
            return False, f"Неверный формат главы: {line}"
        second = int(match.group(2))
        third = match.group(3)
        if second > 59 or (third is not None and int(third) > 59):
            return False, f"Неверное значение времени: {line}"
        points.append(_chapter_seconds(match))
    if points[0] != 0:
        return False, "Первая глава должна начинаться с 00:00."
    if points != sorted(points) or len(set(points)) != len(points):
        return False, "Таймкоды должны идти строго по возрастанию."
    for left, right in zip(points, points[1:]):
        if right - left < 10:
            return False, "Каждая глава должна длиться минимум 10 секунд."
    return True, ""

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