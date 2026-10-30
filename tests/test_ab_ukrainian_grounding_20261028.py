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


def test_bilingual_lexical_subjects_remain_quote_anchored():
    from rg_youtube_control.dialogue_seo import _cross_language_topic_word
    pairs = [
        ("корупція", "коррупция"),
        ("війна", "война"),
        ("звільнення", "увольнение"),
        ("посада", "должность"),
        ("зміни", "смена"),
        ("рішення", "решения"),
        ("влада", "власть"),
        ("пенсії", "пенсии"),
        ("ціни", "цены"),
        ("Крим", "Крым"),
        ("мобілізація", "мобилизация"),
        ("пропаганда", "пропаганда"),
        ("санкції", "санкции"),
    ]
    for ukrainian, russian in pairs:
        assert _cross_language_topic_word(ukrainian)[:5] == (
            _cross_language_topic_word(russian)[:5]
        ), (ukrainian, russian)


def test_translated_topic_without_any_source_word_stays_in_review():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "зарплати", "evidence": "Обсуждали только бензин и цены"},
    ]}]}
    from rg_youtube_control.free_tools import _verified_source_ab_titles
    assert _verified_source_ab_titles(report, "Економіка") == []


def test_ukrainian_editorial_questions_not_false_hallucinations():
    # The headline's topic is evidenced. "оценки прозвучали" is editorial
    # framing, not a factual event that must be spoken verbatim.
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "Корупція", "evidence": "Шойгу коррупция в министерстве"},
        {"topic": "Бензин", "evidence": "На заправках бензин подорожал"},
        {"topic": "Мобілізація", "evidence": "Мобилизация продолжается в регионе"},
    ]}]}
    titles = [
        "Шойгу і корупція: які оцінки пролунали?",
        "Бензин на АЗС: що кажуть співрозмовники?",
        "Мобілізація: які думки називають учасники?",
    ]
    issues = ab_title_issues(titles, report)
    assert not any("без опори на дослівні цитати" in i for i in issues)
    assert not any("не має підтверджених тематичних слів" in i for i in issues)


def test_substantive_unsourced_topic_remains_blocked_with_editorial_framing():
    report = {"blocks": [{"verified": True, "topics": [
        {"topic": "Бензин", "evidence": "На заправках бензин подорожал"},
    ]}]}
    titles = [
        "Бензин та таємні космічні документи: які оцінки пролунали?",
        "Бензин на АЗС: що кажуть співрозмовники?",
        "Мобілізація: які думки називають учасники?",
    ]
    issues = ab_title_issues(titles, report)
    assert any("без опори на дослівні цитати" in i or
               "не має підтверджених тематичних слів" in i
               for i in issues)
