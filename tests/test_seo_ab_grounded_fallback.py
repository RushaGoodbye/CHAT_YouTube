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
