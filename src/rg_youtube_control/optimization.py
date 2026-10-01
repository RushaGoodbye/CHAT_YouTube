from __future__ import annotations

from dataclasses import dataclass

from .config import DONATE_URL, PROJECT_LINKS_URL
from .metadata_audit import normalize_links

@dataclass(frozen=True)
class SafeFix:
    before: str
    after: str
    changes: tuple[str, ...]

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