from rg_youtube_control.free_tools import _grounded_review_title_variants


def test_review_titles_grounded_in_verified_topic():
    variants = _grounded_review_title_variants(
        "ЧАТ РУЛЕТКА",
        ("Шойгу і корупція в РФ. " * 30),
    )
    assert len(variants) == 3
    assert len({x.casefold() for x in variants}) == 3
    assert all(len(x) <= 100 for x in variants)
    assert all(any(topic in x.casefold() for topic in ("шойгу", "корупц")) for x in variants)


def test_no_invented_titles_without_topic_evidence():
    assert _grounded_review_title_variants("ЧАТ РУЛЕТКА", "привіт" * 50) == []


def test_review_ab_recovery_prefers_distinct_transcript_topics():
    from rg_youtube_control.free_tools import _improve_review_ab_distinctness
    from rg_youtube_control.dialogue_seo import ab_title_issues

    repeated = [
        "Шойгу та корупція: чому змінили посаду?",
        "Шойгу та корупція: причини зміни посади",
        "Шойгу та корупція: які причини зміни посади?",
    ]
    transcript = (
        ("Шойгу і корупція. " * 9)
        + ("Зарплати і пенсії людей. " * 8)
        + ("Путін та його рішення. " * 7)
    )
    improved, changed = _improve_review_ab_distinctness(
        "Розмова про Шойгу", repeated, transcript
    )
    assert changed
    assert len(improved) == 3
    assert len(ab_title_issues(improved)) < len(ab_title_issues(repeated))
    assert all("Розмова про Шойгу" != item for item in improved)


def test_review_ab_recovery_never_fabricates_topics_without_source():
    from rg_youtube_control.free_tools import _improve_review_ab_distinctness

    repeated = [
        "Шойгу та корупція: чому змінили посаду?",
        "Шойгу та корупція: причини зміни посади",
        "Шойгу та корупція: які причини зміни посади?",
    ]
    improved, changed = _improve_review_ab_distinctness(
        "Розмова про Шойгу", repeated, "Привіт, як справи?"
    )
    assert not changed
    assert improved == repeated
