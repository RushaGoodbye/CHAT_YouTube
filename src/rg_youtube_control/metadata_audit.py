import re
from dataclasses import dataclass
from .config import (
    DONATE_URL, OLD_DONATE_LINK, OLD_PROJECT_LINKS, PROJECT_LINKS_URL,
)

CHAPTER_RE = re.compile(r"(?m)^\s*\d{1,2}:\d{2}\s+")
HASHTAG_RE = re.compile(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", re.UNICODE)

@dataclass(frozen=True)
class AuditResult:
    score: int
    issues: tuple[str, ...]
    needs_update: bool

def normalize_links(description: str) -> str:
    value = description or ""
    return value.replace(OLD_PROJECT_LINKS, PROJECT_LINKS_URL).replace(
        OLD_DONATE_LINK, DONATE_URL
    )

def audit(description: str, tags: list[str] | None) -> AuditResult:
    value = description or ""
    issues: list[str] = []
    score = 100

    if OLD_PROJECT_LINKS in value or OLD_DONATE_LINK in value:
        issues.append("old_links")
        score -= 30
    if PROJECT_LINKS_URL not in value:
        issues.append("missing_project_link")
        score -= 15
    if DONATE_URL not in value:
        issues.append("missing_donate_link")
        score -= 15
    if len(value.strip()) < 250:
        issues.append("thin_description")
        score -= 15
    if not CHAPTER_RE.search(value):
        issues.append("no_chapters")
        score -= 10

    hashtags = HASHTAG_RE.findall(value)
    if len(hashtags) > 5:
        issues.append("too_many_hashtags")
        score -= 5
    if not tags:
        issues.append("no_tags")
        score -= 10

    return AuditResult(max(score, 0), tuple(issues), bool(issues))