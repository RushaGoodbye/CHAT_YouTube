"""Evidence-gated editorial polish for archived YouTube conversations.

Model topics often over-rank a throwaway joke in chat roulette. Keep full
original evidence for audit, but draft public SEO only from dominant subjects
proven by ORIGINAL transcript text, never from model topic labels alone.
"""
from __future__ import annotations

import re
from typing import Any

from .seo_asr_subjects import shoigu_source_evidence


def _has(source: str, *terms: str) -> bool:
    return any(term in source for term in terms)


def source_grounded_shoigu_package(
    original_title: str, original_transcript: str,
) -> dict[str, Any] | None:
    """Deterministic, high-signal replacement only when core claims are present.

    This is a guarded editorial pattern, NOT a claim that the model's 2
    evidence blocks cover the whole video. No invented transcript quotes
    or timestamps and no claims about Putin's private motives.
    """
    title = str(original_title or "").casefold()
    source = str(original_transcript or "").casefold()
    name_evidence = shoigu_source_evidence(original_transcript)
    if (
        "шойгу" not in title or
        not _has(title, "уволь", "відстав", "отстав", "звільн", "сменил", "змінив") or
        not name_evidence.source_name_supported or len(source) < 350
    ):
        return None
    if not _has(source, "увольн", "уволил", "смени", "должност", "переставил"):
        return None
    if not _has(source, "корруп", "коруп", "взят"):
        return None

    belousov = _has(source, "белоусов", "білоусов", "бєлоусов")
    ivanov = (
        _has(source, "тимур", "тімуp") and
        _has(source, "иванов", "іванов")
    )
    putin = _has(source, "путин", "путін")
    finances = _has(source, "расход", "финанс", "економ", "эконом")

    # Distinct, concrete A/B/C angles. No claims that Shoigu was charged
    # and no vague material such as clothing or incidental personal jokes.
    titles = [
        "ШОЙГУ И КОРРУПЦИЯ: почему россияне спорят о его уходе?",
        "ШОЙГУ ПОКИНУЛ МИНОБОРОНЫ: коррупция или «всё по плану»?",
        (
            "ШОЙГУ И БЕЛОУСОВ: зачем сменили министра обороны России?"
            if belousov else
            "ШОЙГУ И ПУТИН: что россияне думают о кадровом решении?"
            if putin else
            "ШОЙГУ И ЕГО ЗАМЕСТИТЕЛИ: кто отвечает за коррупцию?"
        ),
    ]
    main_title = (
        "ШОЙГУ, КОРРУПЦИЯ И БЕЛОУСОВ: что говорят россияне? | РАША ГУДБАЙ"
        if belousov else
        "УХОД ШОЙГУ: КОРРУПЦИЯ ИЛИ «ВСЁ ПО ПЛАНУ»? | РАША ГУДБАЙ"
    )

    sentences = [
        "Чому Шойгу залишив посаду міністра оборони РФ? "
        "У випуску чат-рулетки «РАША ГУДБАЙ» ведучий запитує росіян, "
        "чи пов'язують вони кадрову перестановку з корупцією, "
        "чи вважають, що «все йде за планом».",
        "Співрозмовники сперечаються про відповідальність Шойгу, "
        "оцінюють рішення влади та висловлюють різні версії його зміни посади.",
    ]
    if ivanov:
        sentences.append(
            "Вони згадують заступників Шойгу та Тимура Іванова в контексті "
            "обговорення корупції, не встановлюючи провину самого Шойгу."
        )
    if belousov:
        sentences.append(
            "Окрема тема розмови — призначення Бєлоусова на посаду "
            "міністра оборони та очікування від цієї кадрової заміни."
        )
    if finances:
        sentences.append(
            "Деякі учасники розмірковують про оборонні витрати "
            "та управління військовими фінансами."
        )
    if putin:
        sentences.append(
            "У розмові також звучать припущення про стосунки Шойгу з Путіним."
        )
    sentences.append(
        "Це позиції учасників розмови, а не підтвердження мотивів "
        "кадрового рішення."
    )
    tags = [
        "Шойгу", "увольнение Шойгу", "коррупция в России",
        "Министерство обороны России", "мнение россиян",
        "чат рулетка", "РАША ГУДБАЙ",
    ]
    if belousov:
        tags.extend(["Белоусов", "Белоусов вместо Шойгу"])
    if ivanov:
        tags.extend(["Тимур Иванов", "заместители Шойгу"])
    if putin:
        tags.append("Путин и Шойгу")
    if finances:
        tags.append("расходы Минобороны")
    return {
        "title": main_title,
        "title_variants": titles,
        "description": " ".join(sentences),
        "tags": tags[:15],
        "chapters": "",
        "needs_review": True,
        "review_reason": (
            "Редакторська пріоритизація головної теми за ОРИГІНАЛОМ; "
            "перевірити ASR-помилки та контекст. Периферійні жарти "
            "виключено з публічного SEO"
        ),
        "editorial_source_relevance": "verbatim-original-transcript-topics",
        "asr_name_evidence": {
            "literal_shoigu": name_evidence.literal_mentions,
            "contextual_approximate_shoigu": name_evidence.contextual_asr_mentions,
            "original_transcript_preserved": True,
        },
    }


_DISTRACTIONS = (
    "рубашк", "рубах", "сорочк", "одежд", "одяг",
    "футболк", "причёск", "зачіск",
)


_INCIDENTAL_HEADLINE = re.compile(
    r"(?i)(?:\bкак\s+дела\b|\bкак\s+поживаете\b|"
    r"\bпривет(?:ствую)?\b|\bздравствуй(?:те)?\b|"
    r"\bдо\s+свидания\b|\bспасибо\s+за\s+(?:разговор|беседу)\b|"
    r"\bяк\s+справи\b|\bдякую\s+за\s+розмову\b|"
    r"\b(?:выглядишь|выглядите|виглядаєш|виглядаєте)\b|"
    r"\b(?:красивый|красивая|красивые|красивий|красива|гарна|гарний)\b|"
    r"\b(?:внешность|зовнішність)\b|"
    r"\b(?:твои|ваши|твої|ваші)\s+(?:глаза|волосы|очі|волосся)\b)"
)

def is_incidental_seo_headline(original_title: str, candidate: str) -> bool:
    """One canonical predicate for desktop GUI and local SEO generator.

    Source conversations may mention clothing or greetings in passing.
    Clothing is legitimate only when it is the source video's own subject.
    """
    candidate_text = " ".join(str(candidate or "").casefold().split())
    source_text = " ".join(str(original_title or "").casefold().split())
    return bool(_INCIDENTAL_HEADLINE.search(candidate_text)) or (
        not _has(source_text, *_DISTRACTIONS)
        and _has(candidate_text, *_DISTRACTIONS)
    )


def off_topic_title_warnings(
    original_title: str, title_variants: list[str],
) -> list[str]:
    """Reject an incidental shirt/appearance anecdote as a main SEO hook.

    The default remains permissive when clothing IS the original video topic.
    """
    return [
        f"Варіант {index} просуває випадкову репліку про зовнішність"
        for index, value in enumerate(title_variants, 1)
        if is_incidental_seo_headline(original_title, value)
    ]
