import re
from dataclasses import dataclass
from .config import DONATE_URL, PROJECT_LINKS_URL

@dataclass(frozen=True)
class Classification:
    category: str
    auto_allowed: bool
    reply: str | None
    reason: str

POLITICAL_TERMS = re.compile(
    r"(?<!\w)(путин\w*|зеленск\w*|трамп\w*|войн\w*|вій\w*|росси\w*|росі\w*|"
    r"украин\w*|україн\w*|крым\w*|крим\w*|донбасс\w*|донбас\w*|"
    r"мобилизац\w*|зсу\w*|всу\w*|нато\w*|выбор\w*|вибор\w*|сво)(?!\w)",
    re.I,
)
THANKS = re.compile(
    r"(?<!\w)(спасиб\w*|дяку\w*|благодар\w*|респект\w*|молодц\w*|молодці\w*)",
    re.I,
)
LINKS = re.compile(
    r"(?<!\w)(ссыл\w*|посилан\w*|link\w*|контакт\w*|телеграм\w*|telegram\w*)",
    re.I,
)
DONATE = re.compile(
    r"(?<!\w)(донат\w*|donat\w*|задонат\w*|підтрим\w*|поддерж\w*|"
    r"реквізит\w*|реквизит\w*)",
    re.I,
)
SCHEDULE = re.compile(
    r"(когда\s+стрим|коли\s+стрім|расписан\w*|розклад\w*|во\s+сколько|о\s+котрій)",
    re.I,
)

def classify(text: str) -> Classification:
    value = " ".join((text or "").split())
    if not value:
        return Classification("review", False, None, "empty")

    if POLITICAL_TERMS.search(value):
        return Classification("review", False, None, "political_or_contested")

    if DONATE.search(value):
        return Classification(
            "donate", True,
            f"Дякуємо за підтримку! Усі варіанти донейту: {DONATE_URL}",
            "donation_request",
        )

    if LINKS.search(value):
        return Classification(
            "links", True,
            f"Усі актуальні посилання проєкту: {PROJECT_LINKS_URL}",
            "project_links_request",
        )

    if SCHEDULE.search(value):
        return Classification(
            "schedule", True,
            f"Актуальний розклад і всі посилання проєкту: {PROJECT_LINKS_URL}",
            "schedule_request",
        )

    if THANKS.search(value) and len(value) <= 220:
        return Classification(
            "thanks", True,
            "Дякуємо за підтримку! 💙💛",
            "simple_thanks",
        )

    return Classification("review", False, None, "manual_review_default")