"""Ukrainian A/B title evidence against Russian-language verbatim quotes."""
from rg_youtube_control.dialogue_seo import ab_title_issues


REPORT = {"blocks": [{"verified": True, "topics": [
    {"topic": "кадрові рішення", "evidence": "Шойгу коррупция и оборона, обсуждали коррупцию"},
    {"topic": "стратегія", "evidence": "Шойгу в МЧС но война и стратегия это другое"},
    {"topic": "посада", "evidence": "Путин и Шойгу, он поменял должность"},
]}]}


def test_ukrainian_titles_can_be_grounded_in_russian_source_quotes():
    titles = [
        "Шойгу та корупція: що кажуть учасники?",
        "Шойгу і війна: чому говорять про стратегію?",
        "Путін і Шойгу: що сталося з посадою?",
    ]
    issues = ab_title_issues(titles, REPORT)
    assert not any("не має підтверджених тематичних слів" in item for item in issues)
    assert not any("кілька формулювань" in item for item in issues)


def test_unverified_family_psychology_is_still_rejected():
    titles = [
        "Шойгу та корупція: що кажуть учасники?",
        "Шойгу і війна: чому говорять про стратегію?",
        "Шойгу: сімейна психологія та особисте життя",
    ]
    issues = ab_title_issues(titles, REPORT)
    assert any("непідтверджену тему сімейної психології" in item for item in issues)


def test_rejects_russian_titles_even_with_relevant_subjects():
    titles = [
        "Шойгу и коррупция: что говорят россияне?",
        "Почему уволили Шойгу: какие реальные причины?",
        "МЧС и военная стратегия: что происходит?",
    ]
    issues = ab_title_issues(titles, REPORT)
    assert sum("не українською" in issue for issue in issues) == 3


def test_unverified_quote_cannot_support_claims():
    report = {"blocks": [
        {"verified": False, "topics": [
            {"topic": "сенсація", "evidence": "На Марсе обнаружили тайные документы"},
        ]},
        {"verified": True, "topics": [
            {"topic": "бензин", "evidence": "Бензин на АЗС стал дороже"},
        ]},
    ]}
    titles = [
        "Бензин на АЗС: як змінилися ціни?",
        "Сенсація на Марсі: чи знайшли документи?",
        "Бензин дорожчає: що кажуть водії?",
    ]
    issues = ab_title_issues(titles, report)
    assert any("не має підтверджених тематичних слів" in x or
               "без опори на дослівні цитати" in x for x in issues)
