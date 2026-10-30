from rg_youtube_control.free_tools import (
    _preserve_current_title_when_candidate_is_not_stronger,
)


def test_legacy_russian_title_does_not_override_ukrainian_proposal():
    before = "Увольнение Шойгу - коррупция или все идет по плану? | РАША ГУДБАЙ"
    proposed = "Звільнення Шойгу: корупція чи кадровий план?"
    assert _preserve_current_title_when_candidate_is_not_stronger(
        before, proposed
    ) == proposed


def test_ukrainian_title_kept_when_only_branding_is_removed():
    before = "Війна та відповідальність посадовців | РАША ГУДБАЙ"
    proposed = "Війна та відповідальність посадовців"
    assert _preserve_current_title_when_candidate_is_not_stronger(
        before, proposed
    ) == before


def test_new_topic_proposal_still_allowed():
    before = "Розмова з росіянами"
    proposed = "Дагестан і контрактна служба: що кажуть співрозмовники?"
    assert _preserve_current_title_when_candidate_is_not_stronger(
        before, proposed
    ) == proposed



def test_grounded_fallback_tags_use_ukrainian():
    from rg_youtube_control.free_tools import _grounded_tags_from_transcript

    tags = _grounded_tags_from_transcript(
        "Увольнение Шойгу - коррупция или все идет по плану? | РАША ГУДБАЙ",
        "Шойгу, коррупция в России. Вопросы россиянам о войне и Украине.",
    )
    assert "звільнення Шойгу" in tags
    assert "корупція в Росії" in tags
    assert "Росія" in tags
    assert "Россия" not in tags
