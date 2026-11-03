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


def test_new_ai_title_name_absent_from_srt_is_review_flagged(monkeypatch):
    import json
    from rg_youtube_control import free_tools

    def proposed(*_args, **_kwargs):
        return json.dumps({
            "title": "Шойгу і кадрові рішення РФ: що відбулося?",
            "title_variants": [
                "Шойгу: яка причина кадрових змін?",
                "Що пояснюють росіяни про чиновників?",
                "Чому кадрові рішення викликають питання?",
            ],
            "description": "У розмові обговорюють ціни та доходи. " * 12,
            "tags": ["росіяни", "доходи", "ціни", "економіка", "чат рулетка",
                     "РАША ГУДБАЙ", "думки", "розмова"],
            "chapters": "",
        }, ensure_ascii=False)

    monkeypatch.setattr(free_tools, "ollama_chat", proposed)
    result = free_tools.generate_seo_package_local(
        current_title="Розмова з росіянами",
        transcript="У нас ціни зростають, зарплати не вистачає. " * 20,
        fast_mode=True,
        transcript_only_preview=True,
    )
    assert result["publication_allowed"] is False
    assert "BLOCKED_TOPIC_MISMATCH" == result["source_alignment_status"]
    assert any(
        "GENERATED_TITLE_SUBJECT_NOT_IN_SRT:ШОЙГУ" == issue
        for issue in result["seo_editorial_quality_flags"]
    )
