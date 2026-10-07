from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommentActionDecision:
    action: str
    category: str
    reason: str
    confidence: str = "medium"


THANKS = re.compile(
    r"(?<!\w)(дяку\w*|спасиб\w*|благодар\w*|респект\w*)(?!\w)",
    re.I,
)
SUPPORT = re.compile(
    r"(підтрим\w*|поддерж\w*|так\s+тримати|так\s+держать|"
    r"кращий\s+канал|лучший\s+канал|ви\s+нам\s+потрібні|"
    r"продовжуйте\s+(?:так|роботу)|продолжайте\s+(?:так|работу))",
    re.I,
)
GREETING = re.compile(
    r"(?<!\w)(привіт|привет|вітаю|здравствуйте|добрий\s+день|"
    r"добрий\s+вечір|добрый\s+день|добрый\s+вечер)(?!\w)",
    re.I,
)
WISHES = re.compile(
    r"(здоров(?:ья|'я|ʼя)|успіх\w*|удач\w*|мирного\s+неба|"
    r"всього\s+(?:доброго|найкращого)|всего\s+(?:доброго|хорошего)|"
    r"бережіть\s+себе|берегите\s+себя|перемог\w*)",
    re.I,
)
PRAISE = re.compile(
    r"(гарн\w*|чудов\w*|класн\w*|классн\w*|цікав\w*|интересн\w*|"
    r"супер\b|браво\b|молодець|молодец|подобається|понрав\w*|"
    r"обожнюю|обожаю|висок\w*\s+рівень)",
    re.I,
)
PATRIOTIC_SUPPORT = re.compile(
    r"(слава\s+україні|героям\s+слава|слава\s+зсу|слава\s+всу|"
    r"все\s+буде\s+україна|україна\s+понад\s+усе|дякую\s+зсу)",
    re.I,
)
HUMOR_OR_REACTION = re.compile(
    r"(😂|🤣|😅|😁|😆|ахаха|хаха|ржу|угар|смішно|смешно|"
    r"насмішил\w*|рассмешил\w*)",
    re.I,
)
INFO_DONATE = re.compile(
    r"(?<!\w)(донат\w*|реквізит\w*|реквизит\w*|paypal\w*|"
    r"monobank\w*|монобанк\w*|де\s+збір|где\s+сбор)(?!\w)",
    re.I,
)
INFO_LINKS = re.compile(
    r"(?<!\w)(посилан\w*|ссыл\w*|link\w*|телеграм\w*|telegram\w*)(?!\w)",
    re.I,
)
INFO_SCHEDULE = re.compile(
    r"(коли\s+(?:стрім|ефір)|когда\s+(?:стрим|эфир)|"
    r"розклад\w*|расписан\w*|во\s+сколько\s+(?:стрим|эфир)|"
    r"о\s+котрій\s+(?:стрім|ефір))",
    re.I,
)
TOXIC = re.compile(
    r"(?<!\w)(дебіл\w*|дебил\w*|ідіот\w*|идиот\w*|чмо\w*|"
    r"туп\w*|дурак\w*|мраз\w*|падл\w*|сволоч\w*|быдл\w*|"
    r"бидл\w*|гівн\w*|говн\w*|кончен\w*)(?!\w)",
    re.I,
)
VIOLENT = re.compile(
    r"(?<!\w)(здох\w*|подох\w*|труп\w*|убит\w*|убить\w*|"
    r"вбит\w*|знищ\w*|уничтож\w*|расстр\w*|їбаш\w*|ебаш\w*)(?!\w)",
    re.I,
)
SPAM = re.compile(
    r"(wonderful\s+channel|timely\s+content|share\s+this\s+video|"
    r"поширюйте\s+це\s+відео)",
    re.I,
)


def _alpha_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]", text or ""))


def decide_comment_action(text: str, *, status: str = "new") -> CommentActionDecision:
    value = " ".join(str(text or "").split())
    if status == "moderation_locked":
        return CommentActionDecision("skip", "moderation_locked", "youtube_moderation", "high")
    if status in {"replied", "ignored"}:
        return CommentActionDecision("skip", status, f"status:{status}", "high")
    if not value:
        return CommentActionDecision("skip", "empty", "empty_comment", "high")

    if SPAM.search(value):
        return CommentActionDecision("skip", "spam", "promotional_or_template_spam", "high")
    if TOXIC.search(value) or VIOLENT.search(value):
        return CommentActionDecision("skip", "toxic_or_risky", "toxic_or_violent_language", "high")

    if INFO_DONATE.search(value):
        return CommentActionDecision("reply", "donate", "safe_info_request:donate", "high")
    if INFO_LINKS.search(value):
        return CommentActionDecision("reply", "links", "safe_info_request:links", "high")
    if INFO_SCHEDULE.search(value):
        return CommentActionDecision("reply", "schedule", "safe_info_request:schedule", "high")

    if THANKS.search(value):
        return CommentActionDecision("reply", "thanks", "safe_social:thanks", "high")
    if SUPPORT.search(value):
        return CommentActionDecision("reply", "support", "safe_social:support", "high")
    if WISHES.search(value):
        return CommentActionDecision("reply", "wishes", "safe_social:wishes", "high")
    if GREETING.search(value):
        return CommentActionDecision("reply", "greeting", "safe_social:greeting", "high")
    if PRAISE.search(value):
        return CommentActionDecision("reply", "episode_praise", "safe_social:praise", "medium")

    if PATRIOTIC_SUPPORT.search(value):
        return CommentActionDecision("like", "patriotic_support", "supportive_patriotic_reaction", "high")

    if HUMOR_OR_REACTION.search(value) or _alpha_count(value) == 0:
        return CommentActionDecision("like", "reaction_or_humor", "reaction_better_than_template_reply", "high")

    if "?" in value:
        return CommentActionDecision("review", "question", "semantic_question", "high")

    return CommentActionDecision(
        "review",
        "substantive_comment",
        "semantic_second_stage",
        "medium",
    )
