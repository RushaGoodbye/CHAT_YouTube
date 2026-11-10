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
