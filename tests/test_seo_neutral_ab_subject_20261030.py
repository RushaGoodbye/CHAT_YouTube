"""Check exact neutral editorial A/B frames against facts, not punctuation/scaffolding.

The only reduced false positives here are the five fixed question suffixes.
Every factual subject must still appear in verified literal source excerpts.
No Ollama, YouTube writes or test network calls.
"""
from rg_youtube_control.dialogue_seo import ab_title_issues, _neutral_source_ab_subject


def _report(*quotes):
    return {"blocks": [
        {"verified": True, "topics": [
            {"topic": "Тема", "summary_uk": "Перевірений фрагмент.",
             "evidence": quote}
        ]}
        for quote in quotes
    ]}


def test_neutral_frames_ignore_only_editorial_words_not_subjects():
    report = _report(
        "Шойгу и коррупция чиновников обсуждались сегодня",
        "Россия и война были главными темами разговора",
        "Коррупция в министерстве обсуждалась отдельно",
    )
    titles = [
        "Корупція: що говорять співрозмовники?",
        "Росія: про що йдеться у чат-рулетці?",
        "Корупція та Росія: про що говорили учасники?",
    ]
    assert ab_title_issues(titles, report) == []


def test_exact_frames_still_reject_invented_subject_with_one_true_word():
    report = _report(
        "Бензин на заправке обсуждали сегодня",
        "Коррупция в министерстве была темой разговора",
    )
    titles = [
        "Бензин: що говорять співрозмовники?",
        "Корупція: про що йдеться у чат-рулетці?",
        "Бензин та таємна ракета: про що говорили учасники?",
    ]
    assert any(
        "підтверджених тематичних" in issue
        for issue in ab_title_issues(titles, report)
    )


def test_unverified_source_cannot_support_neutral_headline():
    report = {
        "blocks": [
            {"verified": False, "topics": [{"evidence": "Росія веде війну"}]},
            {"verified": True, "topics": [{"evidence": "Говорили про бензин"}]},
        ]
    }
    titles = [
        "Бензин: що говорять співрозмовники?",
        "Росія: про що йдеться у чат-рулетці?",
        "Бензин та Росія: про що говорили учасники?",
    ]
    assert any("підтверджених тематичних" in issue for issue in ab_title_issues(titles, report))


def test_not_all_questions_count_as_fixed_editorial_frames():
    assert _neutral_source_ab_subject(
        "Бензин: чому президент приховав секретні дані?"
    ) is None
    assert _neutral_source_ab_subject("Бензин: що говорять співрозмовники?") == "Бензин"


def test_russian_ukrainian_country_inflections_have_same_bilingual_root():
    report = _report("Россияне спорили о России и санкциях",
                     "Бензин на заправке подорожал")
    titles = [
        "Росія: що говорять співрозмовники?",
        "Бензин: про що йдеться у чат-рулетці?",
        "Росія та Бензин: про що говорили учасники?",
    ]
    assert ab_title_issues(titles, report) == []
