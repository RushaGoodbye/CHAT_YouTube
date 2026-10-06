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

DONATE = re.compile(
    r"(?<!\w)(донат\w*|donat\w*|задонат\w*|реквізит\w*|реквизит\w*|"
    r"переказ\w*|перевод\w*|банка\w*|банку\w*|paypal\w*|монобанк\w*|"
    r"monobank\w*|скинут\w*|скинуть\w*|закинут\w*|збір\s+де|де\s+збір)(?!\w)",
    re.I,
)
LINKS = re.compile(
    r"(?<!\w)(ссыл\w*|посилан\w*|link\w*|контакт\w*|телеграм\w*|telegram\w*)",
    re.I,
)
SCHEDULE = re.compile(
    r"(когда\s+стрим|коли\s+стрім|расписан\w*|розклад\w*|"
    r"во\s+сколько\s+(?:стрим|эфир)|о\s+котрій\s+(?:стрім|ефір)|"
    r"коли\s+наступн\w*\s+(?:стрім|ефір))",
    re.I,
)
RETURNING_VIEWER = re.compile(
    r"(давно\s+не\s+(?:смотр|див)|знову\s+з\s+вами|снова\s+с\s+вами|"
    r"повернув\w*|вернул\w*\s+(?:на\s+канал|к\s+вам)|скучал\w*\s+по\s+(?:стрим|канал))",
    re.I,
)
NEW_VIEWER = re.compile(
    r"(вперше\s+(?:дивлю|на\s+канал)|первый\s+раз\s+(?:смотрю|на\s+канале)|"
    r"недавно\s+(?:нашел|знайшов|знайшла)\s+(?:вас|канал)|"
    r"только\s+подписал\w*|щойно\s+підписав\w*|новый\s+зритель|новий\s+глядач)",
    re.I,
)
HEALTH_WISHES = re.compile(
    r"(здоров(?:ья|'я|ʼя)|берегите\s+себя|бережіть\s+себе|не\s+хворійте|"
    r"не\s+болейте|міцного\s+здоров|крепкого\s+здоров)",
    re.I,
)
FUNDRAISING_SUPPORT = re.compile(
    r"((?:дяку\w*|спасиб\w*|підтрим\w*|поддерж\w*).{0,45}(?:збір|збори|сбор|сборы|волонтер))|"
    r"((?:збір|збори|сбор|сборы|волонтер).{0,45}(?:дяку\w*|спасиб\w*|підтрим\w*|поддерж\w*))",
    re.I,
)
EPISODE_PRAISE = re.compile(
    r"((?:випуск|сері\w*|серия|стрім|стрим|ефір|эфир|рубрика|розмова|разговор).{0,55}"
    r"(?:супер|клас\w*|класс\w*|чудов\w*|цікав\w*|интерес\w*|сподобав\w*|понрав\w*|топ\b|висок\w*\s+рівень))|"
    r"((?:супер|клас\w*|класс\w*|чудов\w*|цікав\w*|интерес\w*|сподобав\w*|понрав\w*).{0,55}"
    r"(?:випуск|сері\w*|серия|стрім|стрим|ефір|эфир|рубрика|розмова|разговор))",
    re.I,
)
HOST_COMPLIMENT = re.compile(
    r"((?:олександр|александр|ведуч\w*|ведущ\w*).{0,45}"
    r"(?:супер|красав\w*|молодець|молодец|топ\b|клас\w*|класс\w*|розумн\w*|умн\w*|харизм\w*))|"
    r"((?:супер|красав\w*|молодець|молодец|топ\b|клас\w*|класс\w*).{0,35}"
    r"(?:олександр|александр|ведуч\w*|ведущ\w*))",
    re.I,
)
SUPPORT = re.compile(
    r"(підтримую\s+(?:вас|канал|проект|проєкт)|поддерживаю\s+(?:вас|канал|проект)|"
    r"кращий\s+канал|лучший\s+канал|обожнюю\s+(?:канал|ваші\s+розмови)|"
    r"обожаю\s+(?:канал|ваши\s+разговоры)|продовжуйте\s+(?:так|роботу)|"
    r"продолжайте\s+(?:так|работу)|так\s+тримати|так\s+держать)",
    re.I,
)
HUMOR = re.compile(
    r"(смешно|смішно|ржу|угар|ора?л\s+с\s+этого|насмішил\w*|рассмешил\w*|😂|🤣)",
    re.I,
)
WISHES = re.compile(
    r"(успіх\w*|удач\w*|мирного\s+неба|всього\s+(?:доброго|найкращого)|"
    r"всего\s+(?:доброго|хорошего)|гарного\s+(?:дня|вечора)|хорошего\s+(?:дня|вечера)|"
    r"сил\s+і\s+терпіння|сил\s+и\s+терпения)",
    re.I,
)
GREETING = re.compile(
    r"^(?:привіт|привет|вітаю|здравствуйте|добрий\s+(?:день|вечір)|"
    r"добрый\s+(?:день|вечер)|доброго\s+(?:дня|вечора))[!,.\s🙂😊👋]*$",
    re.I,
)
THANKS = re.compile(
    r"(?<!\w)(спасиб\w*|дяку\w*|благодар\w*|респект\w*|молодц\w*|молодці\w*)",
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
            f"Дякуємо за підтримку! Усі актуальні варіанти донату тут: {DONATE_URL}",
            "donation_request",
        )

    if LINKS.search(value):
        return Classification(
            "links", True,
            f"Усі актуальні посилання проєкту тут: {PROJECT_LINKS_URL}",
            "project_links_request",
        )

    if SCHEDULE.search(value):
        return Classification("schedule", True, None, "schedule_request")

    if RETURNING_VIEWER.search(value):
        return Classification("returning_viewer", True, None, "returning_viewer")

    if NEW_VIEWER.search(value):
        return Classification("new_viewer", True, None, "new_viewer")

    if HEALTH_WISHES.search(value):
        return Classification("health_wishes", True, None, "health_wishes")

    if FUNDRAISING_SUPPORT.search(value):
        return Classification(
            "fundraising_support", True, None, "fundraising_support"
        )

    if EPISODE_PRAISE.search(value):
        return Classification("episode_praise", True, None, "episode_praise")

    if HOST_COMPLIMENT.search(value):
        return Classification("host_compliment", True, None, "host_compliment")

    if SUPPORT.search(value):
        return Classification("support", True, None, "channel_support")

    if WISHES.search(value):
        return Classification("wishes", True, None, "good_wishes")

    if GREETING.search(value):
        return Classification("greeting", True, None, "greeting")

    if HUMOR.search(value) and len(value) <= 180:
        return Classification("humor", True, None, "humor_reaction")

    if THANKS.search(value) and len(value) <= 220:
        return Classification(
            "thanks", True,
            "Дякуємо за підтримку! 💙💛",
            "simple_thanks",
        )

    return Classification("review", False, None, "manual_review_default")
