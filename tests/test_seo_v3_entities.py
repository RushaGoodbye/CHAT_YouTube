"""Source-only spelling validation for mixed-language transcript entities."""
from rg_youtube_control.seo_v3_entities import unsupported_names_v3


def _draft(description):
    return {"title": "", "description": description,
            "title_variants": [], "tags": []}


def _source(*quotes):
    return [{"quote": quote} for quote in quotes]


def test_russian_transcript_supports_ukrainian_locative_spelling():
    assert unsupported_names_v3(
        _draft("У розмові згадали життя у Новосибірську."),
        _source("Говорили о жизни в Новосибирске."),
    ) == []
    assert unsupported_names_v3(
        _draft("Також згадали становище в Росії."),
        _source("Ситуация в России меняется."),
    ) == []


def test_unrelated_locative_and_misspelled_person_remain_blocked():
    assert "Новосибірську" in unsupported_names_v3(
        _draft("У розмові згадали життя у Новосибірську."),
        _source("Говорили только об автомашинах."),
    )
    assert "Шайгурова" in unsupported_names_v3(
        _draft("Співрозмовник питає про звільнення Шайгурова."),
        _source("как вы оцениваете увольнение шайгумаров"),
    )
    assert "Сидаренка" in unsupported_names_v3(
        _draft("Співрозмовник питає про Сидаренка."),
        _source("вспоминал Сидоренка"),
    )


def test_proper_noun_in_a_different_nonlocative_context_is_not_whitelisted():
    assert "Новосибірську" in unsupported_names_v3(
        _draft("Спікер зазначив Новосибірську."),
        _source("Я приехал из Новосибирска."),
    )
