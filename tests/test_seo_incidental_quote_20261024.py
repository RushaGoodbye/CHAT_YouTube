"""Prevent incidental small talk and appearance remarks becoming fallback SEO titles."""
from rg_youtube_control.free_tools import (
    _incidental_ab_quote,
    _source_quote_ab_titles,
)


def test_smalltalk_and_appearance_quotes_never_become_hooks():
    for phrase in (
        "Привет, как дела у тебя сегодня?",
        "Ты выглядишь сегодня очень красиво, так держать.",
        "Твоя внешность меня сегодня очень удивляет.",
        "Дякую за розмову, до наступної зустрічі.",
        "Ваши глаза очень красивые на этой фотографии.",
    ):
        assert _incidental_ab_quote(phrase), phrase


def test_substantive_political_and_economic_remarks_remain_eligible():
    for phrase in (
        "В нашем регионе на заправках бензин снова подорожал, теперь водителям тяжело.",
        "Решения правительства о новых налогах вызывают обсуждения в городе.",
        "Какая ответственность за удары по энергетике и почему люди молчат?",
        "Зовнішня політика залежить від конкретних рішень парламенту.",
    ):
        assert not _incidental_ab_quote(phrase), phrase


def test_fallback_skips_appearance_and_keeps_distinct_dialogue_topics():
    evidence = [
        [
            ("Зовнішність", "Ты выглядишь сегодня очень красиво, такую красоту не забыть никогда."),
            ("Бензин", "На автозаправочных станциях бензин подорожал после изменений налоговой политики."),
        ],
        [
            ("Освіта", "В школах сокращают учебные часы и родители обсуждают качество образования."),
        ],
        [
            ("Робота", "В небольших городах закрываются предприятия и работники ищут новую работу."),
        ],
        [
            ("Інфраструктура", "После новых ограничений местные дороги остаются без ремонта много месяцев."),
        ],
    ]
    report = {
        "blocks": [
            {
                "verified": True,
                "start_stamp": f"{index * 12:02d}:00",
                "topics": [
                    {"topic": topic, "evidence": quote}
                    for topic, quote in block
                ],
            }
            for index, block in enumerate(evidence)
        ]
    }
    titles = _source_quote_ab_titles(report)
    assert len(titles) == 3
    assert all("выглядишь" not in title.casefold() for title in titles)
