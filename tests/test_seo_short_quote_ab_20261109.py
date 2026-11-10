from rg_youtube_control import free_tools


def test_short_literal_quotes_remain_eligible_for_review(monkeypatch):
    quotes = [
        "Ми цього не підтримуємо",
        "Звідки у вас такі цифри",
        "Про це треба говорити",
    ]
    report = {
        "blocks": [
            {
                "verified": True,
                "start_stamp": f"0{i}:00",
                "topics": [{"topic": "Розмова", "evidence": quote}],
            }
            for i, quote in enumerate(quotes)
        ]
    }
    # The source selection should not discard meaningful 3-4 word
    # quotations solely for failing the old 30-character cutoff.
    monkeypatch.setattr(free_tools, "ab_title_issues", lambda titles, report: [])
    titles = free_tools._source_quote_ab_titles(report)
    assert len(titles) == 3
    assert all(any(q in title for q in quotes) for title in titles)


def test_short_interjections_are_not_headline_evidence(monkeypatch):
    report = {
        "blocks": [
            {"verified": True, "topics": [{"topic": "Розмова", "evidence": "Так"}]},
            {"verified": True, "topics": [{"topic": "Розмова", "evidence": "Ну добре"}]},
            {"verified": True, "topics": [{"topic": "Розмова", "evidence": "Ні"}]},
        ]
    }
    monkeypatch.setattr(free_tools, "ab_title_issues", lambda titles, report: [])
    assert free_tools._source_quote_ab_titles(report) == []



def test_generic_primary_title_detection_is_not_triggered_by_specific_event():
    flags = free_tools._seo_editorial_preview_flags
    assert "GENERIC_PRIMARY_TITLE" in flags(
        "Що кажуть росіяни?", "", [], [],
    )
    assert "GENERIC_PRIMARY_TITLE" in flags(
        "Розмова співрозмовників", "", [], [],
    )
    assert "GENERIC_PRIMARY_TITLE" not in flags(
        "Що кажуть росіяни про відставку Шойгу?", "", [], [],
    )
    assert "GENERIC_PRIMARY_TITLE" not in flags(
        "Чому співрозмовник не вірить заявам про зарплати?", "", [], [],
    )



def test_specific_generated_title_replaces_legacy_generic_title():
    old = "Що кажуть росіяни?"
    candidate = "Росіянин розповів про зарплату та ціни у своєму місті"
    selected = free_tools._preserve_current_title_when_candidate_is_not_stronger(
        old, candidate,
    )
    assert selected == candidate


def test_specific_legacy_title_not_replaced_with_generic_model_output():
    old = "Що каже росіянин про зарплату у своєму місті?"
    candidate = "Що кажуть росіяни?"
    selected = free_tools._preserve_current_title_when_candidate_is_not_stronger(
        old, candidate,
    )
    assert selected == old


def test_ab_angles_drop_near_identical_main_title_and_keep_different_hooks():
    primary = "Чому росіянин не вірить обіцянкам про зарплати?"
    proposals = [
        "Чому росіянин не вірить обіцянкам про зарплати!",
        "Чому росіянин не вірить обіцянкам про зарплати?",
        "Скільки отримує співрозмовник і на що вистачає грошей?",
        "Що він відповів на запитання про ціни?",
        "Де зникають гроші після отримання зарплати?",
    ]
    variants = free_tools._select_diverse_title_variants(primary, proposals)
    assert len(variants) == 3
    assert all(value not in proposals[:2] for value in variants)
    assert len({value.casefold() for value in variants}) == 3


def test_ab_angles_do_not_pad_with_synthetic_generic_titles():
    variants = free_tools._select_diverse_title_variants(
        "Розмова про пенсії",
        ["Розмова про пенсії!", "Розмова про пенсії?"],
    )
    assert variants == []
