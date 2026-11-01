from rg_youtube_control.free_tools import _seo_title_source_conflicts


def test_title_and_srt_subject_conflict_is_flagged_for_review():
    flags = _seo_title_source_conflicts(
        "Гордість і бідність: чому чеченці ведуть себе так?",
        "[05:38] Путин объявит всеобщую мобилизацию. "
        "[12:40] Це про пенсії та зарплату.",
    )
    assert "TITLE_SUBJECT_NOT_IN_SRT:ЧЕЧЕН" in flags


def test_russian_srt_spelling_supports_ukrainian_named_title_subject():
    assert _seo_title_source_conflicts(
        "Шойгу і Бєлоусов: що кажуть співрозмовники?",
        "[15:05] Смена должности Шойгу и назначение Белоусова.",
    ) == []


def test_missing_srt_or_untargeted_title_is_not_misclassified():
    assert _seo_title_source_conflicts("Питання та відповіді", "Війна і політика") == []
    assert _seo_title_source_conflicts("Шойгу: що змінилося?", "") == []


def test_hamas_israel_public_title_must_match_original_srt():
    flags = _seo_title_source_conflicts(
        "ІЗРАЇЛЬ — ГЕРОЇ! АЛЕ РОСІЯ ПІДТРИМАЛА ХАМАС",
        "Обговорювали будинок та як люди голосували за президента.",
    )
    assert any("ХАМАС" in code for code in flags)
    assert any("ІЗРАЇЛ" in code for code in flags)


def test_convicts_and_schools_title_is_blocked_when_absent_from_captions():
    flags = _seo_title_source_conflicts(
        "Могут ли ОСУЖДЕННЫЕ преподавать в ШКОЛАХ рф?",
        "Це розмова про суспільство та іншу ситуацію.",
    )
    assert any("ОСУЖДЕН" in code for code in flags)
    assert any("ШКОЛ" in code for code in flags)


def test_named_russian_title_subjects_present_in_full_srt_are_allowed_for_review():
    assert _seo_title_source_conflicts(
        "Шойгу, ХАМАС та ІЗРАЇЛЬ: про що йдеться?",
        "Шойгу, ХАМАС та Израиль були згадані у розмові.",
    ) == []
