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


BASE_HASHTAGS = ("#рашагудбай", "#чатрулетка")
HASHTAG_ONLY_LINE_RE = re.compile(
    r"^\s*(?:#[\wА-Яа-яІіЇїЄєҐґ]+\s*){1,15}$", re.UNICODE
)
TOPIC_HASHTAGS = (
    (("зсу", "всу", "збройн", "вооруженн"), "#зсу"),
    (("підтрим", "поддерж"), "#підтримказсу"),
    (("розіграш", "розыгрыш", "лот"), "#розіграш"),
    (("бензин", "топлив", "азс"), "#бензин"),
    (("эконом", "економ", "econom"), "#экономикароссии"),
    (("санкц", "sanction"), "#санкции"),
    (("мобилиз", "мобіліз", "mobiliz"), "#мобилизация"),
    (("путин", "путін", "putin"), "#путин"),
    (("войн", "війн", " war ", "war:"), "#война"),
    (("росси", "росі", "russia", "russian"), "#россия"),
    (("украин", "україн", "ukrain"), "#украина"),
    (("дрон", "бпла", "безпілот", "drone"), "#дроны"),
    (("нефт", "нафт", "нпз", " oil ", "refiner"), "#нефть"),
    (("крым", "крим", "crimea"), "#крым"),
    (("донбасс", "донбас", "donbas"), "#донбасс"),
    (("армия", "армі", " army ", "military"), "#армия"),
    (("armenian", "armenia", "армян", "вірмен", "вермен"), "#армения"),
    (("cheburashka", "чебураш"), "#чебурашка"),
)

GENERIC_TOPIC_HASHTAGS = {"#россия", "#украина", "#война"}

DEEP_REVIEW_ISSUES = {
    "thin_description",
    "no_chapters",
    "no_tags",
}


def needs_deep_review(issues: list[str] | tuple[str, ...]) -> bool:
    return bool(DEEP_REVIEW_ISSUES.intersection(set(issues)))


TITLE_BOILERPLATE_RE = re.compile(
    r"(?iu)\b(?:чат\s*рулетка|раша\s*гудбай|russia\s*goodbye|"
    r"russiagoodbye|стрим|эфир|ефір|stream)\b"
)
TITLE_TOPIC_STOPWORDS = {
    "это", "этот", "эта", "эти", "как", "что", "кто", "где", "когда", "почему",
    "зачем", "или", "для", "про", "при", "без", "под", "над", "между", "после",
    "перед", "его", "ее", "её", "они", "она", "оно", "мы", "вы", "ты", "я",
    "мой", "моя", "мои", "твой", "твоя", "наш", "ваш", "есть", "нет", "был",
    "была", "были", "будет", "будут", "уже", "еще", "ещё", "очень", "просто",
    "снова", "опять", "реально", "вообще", "теперь", "сегодня", "завтра",
    "від", "для", "про", "після", "перед", "його", "її", "вони", "вона",
    "ми", "ви", "ти", "мій", "моя", "наша", "ваша", "є", "нема", "буде",
    "будуть", "вже", "ще", "дуже", "просто", "сьогодні", "завтра",
    "происходит", "произошло", "говорит", "говорят", "разговор", "мнение",
    "история", "видео", "вопрос", "ответ", "живешь", "живёшь",
    "відбувається", "сталося", "говорить", "кажуть", "розмова", "думка",
    "історія", "відео", "питання", "відповідь",
    "the", "and", "from", "with", "without", "into", "about", "after", "before",
    "this", "that", "these", "those", "what", "who", "where", "when", "why",
    "how", "your", "you", "they", "their", "his", "her", "our", "my", "not",
    "favorite", "real", "critique", "past", "found", "origin", "identity",
    "сильный", "сильная", "сильное", "сильные", "сильний", "сильна", "сильне",
    "crisis", "video", "live", "stream", "character", "question", "answer",
    "story", "presidents", "president", "people", "thing", "things",
}


def _title_topic_hashtag(title: str) -> str:
    """Extract a concrete title topic only when confidence is high enough.

    This deliberately avoids turning generic English title words such as
    "Favorite" or "Critique" into hashtags.
    """
    cleaned = TITLE_BOILERPLATE_RE.sub(" ", title or "")
    generic_places = {
        "россия", "россии", "россию", "украина", "украине", "украину",
        "россиянин", "россиянина", "россиянином", "россияне", "россиянами",
        "россиянка", "россиянки",
        "russia", "russian", "ukraine", "ukrainian",
    }
    candidates: list[tuple[int, int, str]] = []
    separator_at = max(cleaned.find(":"), cleaned.find(" - "), cleaned.find(" — "))

    for index, match in enumerate(
        re.finditer(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9]+", cleaned, re.UNICODE)
    ):
        token = match.group(0)
        value = token.casefold()
        if len(value) < 4 or value.isdigit():
            continue
        if value in TITLE_TOPIC_STOPWORDS or value in generic_places:
            continue
        if value.endswith(("ться", "тися")):
            continue

        letters = "".join(ch for ch in token if ch.isalpha())
        is_all_caps = bool(letters) and letters.upper() == letters and letters.lower() != letters
        is_capitalized = bool(letters) and letters[0].isupper()
        after_separator = separator_at >= 0 and match.start() > separator_at

        score = 0
        if is_all_caps:
            score += 5
        elif is_capitalized:
            score += 2
        if after_separator:
            score += 2
        if len(value) >= 8:
            score += 1

        # Lower-case words are accepted only when they are unusually specific.
        if not is_all_caps and not is_capitalized and len(value) >= 10:
            score += 2

        if score >= 2:
            candidates.append((score, -index, value))

    if not candidates:
        return ""

    candidates.sort(reverse=True)
    return "#" + candidates[0][2]

def optimized_hashtags(
    title: str,
    description: str = "",
) -> tuple[str, ...]:
    """Return two project hashtags plus one precise thematic hashtag.

    The title is the strongest topic signal. A concrete high-confidence title
    entity (for example ШОЙГУ) must not be displaced by a broad word that only
    appears in the generated description (for example экономика).
    """
    title_text = str(title or "").casefold()
    description_text = str(description or "").casefold()

    title_topic = ""
    title_generic = ""
    for needles, hashtag in TOPIC_HASHTAGS:
        if not any(needle in title_text for needle in needles):
            continue
        if hashtag in GENERIC_TOPIC_HASHTAGS:
            if not title_generic:
                title_generic = hashtag
            continue
        title_topic = hashtag
        break

    if not title_topic:
        title_topic = _title_topic_hashtag(title)

    if title_topic:
        return (*BASE_HASHTAGS, title_topic)

    description_topic = ""
    description_generic = ""
    for needles, hashtag in TOPIC_HASHTAGS:
        if not any(needle in description_text for needle in needles):
            continue
        if hashtag in GENERIC_TOPIC_HASHTAGS:
            if not description_generic:
                description_generic = hashtag
            continue
        description_topic = hashtag
        break

    topic = description_topic or title_generic or description_generic or "#россия"
    return (*BASE_HASHTAGS, topic)

def _optimize_hashtag_lines(description: str, title: str) -> tuple[str, bool]:
    if not title.strip():
        return description, False
    desired = " ".join(optimized_hashtags(title, description))
    lines = description.splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        if HASHTAG_ONLY_LINE_RE.fullmatch(line):
            if not replaced:
                output.append(desired)
                replaced = True
            continue
        output.append(line)
    value = "\n".join(output)
    if replaced:
        return value, value != description
    value = value.rstrip()
    if value:
        value += "\n\n"
    value += desired
    return value, True

SAFE_LINK_ISSUES = frozenset({
    "old_links",
    "missing_project_link",
    "missing_donate_link",
    "too_many_hashtags",
})


def has_safe_link_issue(issues: list[str] | tuple[str, ...]) -> bool:
    return bool(SAFE_LINK_ISSUES.intersection(issues))


def is_safe_archive_candidate(issues: list[str] | tuple[str, ...]) -> bool:
    """Safe archive batches must not mix in videos with title-language issues."""
    issue_set = set(issues)
    return (
        bool(SAFE_LINK_ISSUES.intersection(issue_set))
        and "latin_title_review" not in issue_set
        and "invalid_description" not in issue_set
    )



LEGACY_SERVICE_HINTS = (
    "КАНАЛ ДЛЯ СТРИМІВ",
    "КАНАЛ ДЛЯ СТРИМОВ",
    "СТАТИ ПАРТНЕРОМ ПРОЕКТУ",
    "СТАТИ ПАРТНЕРОМ ПРОЄКТУ",
    "ПІДТРИМАТИ АВТОРА",
    "ПОДДЕРЖАТЬ АВТОРА",
    "ЗБІР ТРИВАЄ",
    "СБОР ПРОДОЛЖАЕТСЯ",
    "ДЛЯ ЗСУ",
    "НА РОЗВИТОК ПРОЕКТУ",
    "НА РОЗВИТОК ПРОЄКТУ",
    "КРИПТОГАМАНЕЦЬ",
    "КРИПТОКОШЕЛЕК",
    "ТЕЛЕГРАМ КАНАЛ ПРОЕКТУ",
    "ТЕЛЕГРАМ КАНАЛ ПРОЄКТУ",
    "TIKTOK КАНАЛ",
    "ПРОЕКТ «ХОЧУ ЖИТЬ»",
    'ПРОЕКТ "ХОЧУ ЖИТЬ"',
)

CANONICAL_SERVICE_MARKERS = (
    "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:",
    "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:",
)


TRAILING_SECTION_LABEL_RE = re.compile(
    r"(?im)\\n{0,2}\\s*(?:ТЕГИ|ТЕГИ:|TAGS|TAGS:)\\s*$"
)


def _strip_trailing_section_label(value: str) -> tuple[str, bool]:
    before = (value or "").rstrip()
    after = TRAILING_SECTION_LABEL_RE.sub("", before).rstrip()
    return after, after != before


def _looks_like_legacy_service_prefix(value: str) -> bool:
    upper = (value or "").upper()
    return any(hint in upper for hint in LEGACY_SERVICE_HINTS)


def _strip_existing_canonical_service_blocks(value: str) -> str:
    """Remove previously generated canonical service blocks before rebuilding them."""
    lines = (value or "").splitlines()
    output: list[str] = []
    skip_next_url = False
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if any(upper == marker.upper() for marker in CANONICAL_SERVICE_MARKERS):
            skip_next_url = True
            continue
        if skip_next_url:
            if stripped in {PROJECT_LINKS_URL, DONATE_URL}:
                skip_next_url = False
                continue
            if stripped:
                skip_next_url = False
        output.append(line)
    return "\n".join(output).strip()


def _strip_legacy_service_prefix(description: str, title: str) -> tuple[str, bool]:
    """Drop the old donation/social boilerplate when the real video body follows it.

    Older RG descriptions often start with a large service block and then repeat
    the exact video title. When that pattern is present, everything before the
    title is legacy boilerplate and is safe to replace with the canonical links.
    """
    value = (description or "").strip()
    clean_title = (title or "").strip()
    if not value or not clean_title or not _looks_like_legacy_service_prefix(value):
        return value, False

    lines = value.splitlines()
    title_cf = clean_title.casefold()
    for index, line in enumerate(lines):
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.casefold() == title_cf:
            trimmed = "\n".join(lines[index:]).strip()
            return trimmed, trimmed != value

    return value, False


def _append_canonical_service_block(value: str) -> str:
    body = _strip_existing_canonical_service_blocks(value).rstrip()
    service = (
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:\n"
        f"{PROJECT_LINKS_URL}\n\n"
        "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:\n"
        f"{DONATE_URL}"
    )
    return f"{body}\n\n{service}".strip() if body else service



def safe_description_needs_content_package(
    description: str,
    title: str = "",
    *,
    min_body_chars: int = 160,
    min_body_letters: int = 80,
) -> bool:
    """Return True when a cleaned safe description has no meaningful video body.

    Old RG descriptions can consist almost entirely of donation/social boilerplate,
    followed by the title and hashtags. After replacing that boilerplate with the
    canonical links, such a description is technically clean but still too thin
    to publish as an SEO result. Those videos must go through transcript/content
    review instead of the safe-link batch.
    """
    value = (description or "").strip()
    if not value:
        return True

    cut = len(value)
    for marker in CANONICAL_SERVICE_MARKERS:
        pos = value.find(marker)
        if pos >= 0:
            cut = min(cut, pos)
    body = value[:cut].strip()

    clean_title = (title or "").strip().casefold()
    kept: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if HASHTAG_ONLY_LINE_RE.fullmatch(stripped):
            continue
        if clean_title and stripped.casefold() == clean_title:
            continue
        kept.append(stripped)

    meaningful = "\n".join(kept).strip()
    letters = len(re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґЁё]", meaningful))
    return (
        len(meaningful) < max(1, int(min_body_chars))
        or letters < max(1, int(min_body_letters))
    )


def safe_description_fix(description: str, title: str = "") -> SafeFix:
    before = description or ""
    after = normalize_links(before)
    changes: list[str] = []

    if after != before:
        changes.append("замінено старі посилання")

    after, legacy_removed = _strip_legacy_service_prefix(after, title)
    if legacy_removed:
        changes.append("прибрано застарілий блок посилань і реквізитів")

    before_service = after
    after = _append_canonical_service_block(after)
    if after != before_service:
        changes.append("оновлено єдиний блок актуальних посилань")

    after, hashtags_changed = _optimize_hashtag_lines(after, title)
    if hashtags_changed:
        changes.append("оновлено хештеги")

    after, label_removed = _strip_trailing_section_label(after)
    if label_removed:
        changes.append("прибрано службовий підпис тегів")

    return SafeFix(
        before=before,
        after=after,
        changes=tuple(dict.fromkeys(changes)),
    )


ENGLISH_SUMMARY_MARKER_RE = re.compile(
    r"^\s*(?:🇬🇧\s*)?ENGLISH\s+SUMMARY\s*:\s*$",
    re.IGNORECASE,
)
INLINE_HASHTAG_RE = re.compile(
    r"(?<![\w/])#([\wА-Яа-яІіЇїЄєҐґ]+)",
    re.UNICODE,
)


def _keep_only_canonical_hashtag_line(description: str) -> tuple[str, bool]:
    lines = (description or "").splitlines()
    canonical_seen = False
    changed = False
    output: list[str] = []
    for line in lines:
        if HASHTAG_ONLY_LINE_RE.fullmatch(line):
            if not canonical_seen:
                output.append(line)
                canonical_seen = True
            else:
                changed = True
            continue
        cleaned = INLINE_HASHTAG_RE.sub(r"\1", line)
        if cleaned != line:
            changed = True
        output.append(cleaned)
    value = "\n".join(output).strip()
    return value, changed


def sanitize_imported_package_description(
    description: str,
    title: str = "",
) -> SafeFix:
    """Remove an explicit English duplicate when a Ukrainian body exists."""
    before = (description or "").strip()
    lines = before.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if ENGLISH_SUMMARY_MARKER_RE.fullmatch(line)
        ),
        None,
    )
    if start is None:
        return SafeFix(before=before, after=before, changes=())

    prefix = "\n".join(lines[:start]).strip()
    cyrillic_letters = len(
        re.findall(r"[А-Яа-яІіЇїЄєҐґ]", prefix, re.UNICODE)
    )
    if len(prefix) < 250 or cyrillic_letters < 80:
        return SafeFix(before=before, after=before, changes=())

    end = len(lines)
    service_markers = (
        "УСІ АКТИВНІ ПОСИЛАННЯ ПРОЄКТУ:",
        "УСІ ВАРІАНТИ ВІДПРАВИТИ ДОНЕЙТ:",
    )
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if (
            HASHTAG_ONLY_LINE_RE.fullmatch(lines[index])
            or any(stripped.startswith(marker) for marker in service_markers)
        ):
            end = index
            break

    after = "\n".join(lines[:start] + lines[end:]).strip()
    after = re.sub(r"\n{3,}", "\n\n", after)
    changes: list[str] = ["видалено дубль англійського опису"]

    safe_fix = safe_description_fix(after, title)
    after = safe_fix.after
    changes.extend(safe_fix.changes)

    after, hashtags_changed = _keep_only_canonical_hashtag_line(after)
    if hashtags_changed:
        changes.append("прибрано зайві inline-хештеги")

    after, label_removed = _strip_trailing_section_label(after)
    if label_removed:
        changes.append("прибрано службовий підпис тегів")

    after = re.sub(r"\n{3,}", "\n\n", after).strip()
    return SafeFix(
        before=before,
        after=after,
        changes=tuple(dict.fromkeys(changes)),
    )


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
    if "latin_title_review" in issue_set:
        return 900, "НАЗВА"
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


def youtube_title_errors(title: str) -> tuple[str, ...]:
    """Validate title against YouTube Data API snippet constraints."""
    value = title or ""
    errors: list[str] = []
    if len(value) > 100:
        errors.append(
            f"Назва має {len(value)} символів. YouTube дозволяє не більше 100."
        )
    if "<" in value or ">" in value:
        errors.append("Назва містить заборонені YouTube символи < або >.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        errors.append("Назва містить некоректну UTF-8 послідовність.")
    return tuple(errors)


def normalize_package_tags(
    tags: list[str] | tuple[str, ...] | None,
    *,
    max_tags: int = 15,
    max_chars: int = 500,
) -> list[str]:
    """Deduplicate package tags and keep them within YouTube limits."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        value = " ".join(str(raw or "").split()).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        candidate = result + [value]
        if len(", ".join(candidate)) > max_chars:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= max_tags:
            break
    return result


def youtube_description_errors(description: str) -> tuple[str, ...]:
    """Validate description against YouTube Data API snippet constraints."""
    value = description or ""
    errors: list[str] = []
    try:
        byte_len = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        byte_len = 0
        errors.append("Опис містить некоректну UTF-8 послідовність.")
    if byte_len > 5000:
        errors.append(
            f"Опис займає {byte_len} байт. YouTube дозволяє не більше 5000."
        )
    if "<" in value or ">" in value:
        errors.append("Опис містить заборонені YouTube символи < або >.")
    return tuple(errors)


def validate_content_package(
    title: str,
    description: str,
    chapters: str,
    tags: list[str] | None,
    title_variants: list[str] | None = None,
    *,
    chapters_optional: bool = False,
) -> PackageCheck:
    errors: list[str] = []
    warnings: list[str] = []

    clean_title = (title or "").strip()
    clean_description = safe_description_fix(
        (description or "").strip(),
        clean_title,
    ).after
    clean_tags = normalize_package_tags(tags)
    clean_variants = [
        str(item).strip()
        for item in (title_variants or [])
        if str(item).strip()
    ]

    if not clean_title:
        errors.append("Назва порожня.")
    else:
        errors.extend(youtube_title_errors(clean_title))

    if not clean_description:
        errors.append("Опис порожній.")
    else:
        errors.extend(youtube_description_errors(clean_description))
        if len(clean_description) < 250:
            warnings.append("Опис коротший за 250 символів.")

    if PROJECT_LINKS_URL not in clean_description:
        warnings.append("В описі немає актуального посилання проєкту.")
    if DONATE_URL not in clean_description:
        warnings.append("В описі немає актуального посилання на донат.")

    chapter_ok, chapter_message = validate_chapters(chapters)
    if not chapter_ok:
        errors.append(chapter_message)
    elif not chapters.strip() and not chapters_optional:
        warnings.append("Розділи не заповнені.")

    if not clean_tags:
        errors.append("Теги не заповнені. Пакет не можна застосувати.")
    elif len(clean_tags) < 8:
        errors.append("Потрібно щонайменше 8 релевантних тегів.")
    else:
        tag_chars = len(", ".join(clean_tags))
        if tag_chars > 500:
            errors.append(
                f"Теги займають приблизно {tag_chars} символів. "
                "Потрібно вкластися у 500."
            )

    hashtags = re.findall(r"(?<!\w)#[\wА-Яа-яІіЇїЄєҐґ]+", clean_description)
    if len(hashtags) != 3:
        warnings.append("В описі бажано мати рівно 3 релевантні хештеги.")

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
    detected_body, detected_chapters = extract_chapters_from_description(body)
    if detected_chapters:
        body = detected_body

    chapter_block = chapters.strip() or detected_chapters
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