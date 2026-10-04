import re
from dataclasses import dataclass
from .config import (
    DONATE_URL, OLD_DONATE_LINK, OLD_PROJECT_LINKS, PROJECT_LINKS_URL,
)

CHAPTER_RE = re.compile(r"(?m)^\s*\d{1,2}:\d{2}\s+")
HASHTAG_RE = re.compile(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", re.UNICODE)
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
CYRILLIC_LETTER_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґЁё]")


def title_script_profile(title: str) -> str:
    """Classify a title as latin, cyrillic, mixed, or unknown.

    RG channels are Russian/Ukrainian spoken-content channels, so a strongly
    Latin title is a review signal, not something safe automation should create.
    """
    value = title or ""
    latin = len(LATIN_LETTER_RE.findall(value))
    cyrillic = len(CYRILLIC_LETTER_RE.findall(value))
    recognized = latin + cyrillic
    if recognized < 8:
        return "unknown"
    if latin >= 8 and latin / recognized >= 0.75:
        return "latin"
    if cyrillic >= 8 and cyrillic / recognized >= 0.60:
        return "cyrillic"
    return "mixed"


def blocks_automatic_title_language_change(
    current_title: str,
    new_title: str,
) -> bool:
    """Block an automatic Cyrillic -> Latin title replacement."""
    return (
        title_script_profile(current_title) == "cyrillic"
        and title_script_profile(new_title) == "latin"
    )

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

def _duration_seconds(value: str | None) -> int:
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        str(value or ""),
    )
    if not match:
        return 0
    return (
        int(match.group(1) or 0) * 3600
        + int(match.group(2) or 0) * 60
        + int(match.group(3) or 0)
    )


def audit(
    description: str,
    tags: list[str] | None,
    title: str = "",
    duration: str | None = None,
) -> AuditResult:
    value = description or ""
    issues: list[str] = []
    score = 100

    if title and title_script_profile(title) == "latin":
        issues.append("latin_title_review")
        score -= 15

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
    duration_seconds = _duration_seconds(duration)
    short_by_duration = 0 < duration_seconds <= 60
    short_by_label = (
        0 < duration_seconds <= 180
        and "#shorts" in (title or "").casefold()
    )
    if not CHAPTER_RE.search(value) and not (short_by_duration or short_by_label):
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