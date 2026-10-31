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
