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
