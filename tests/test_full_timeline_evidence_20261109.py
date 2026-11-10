from rg_youtube_control.dialogue_seo import split_timeline, _validate_topics


def test_all_srt_rows_are_preserved_across_windows():
    rows = [
        {"start": i * 18.0, "duration": 2.0, "text": f"Змістовна репліка номер {i} про джерела інформації"}
        for i in range(75)
    ]
    blocks = split_timeline(rows, max_chars=280, max_span_seconds=120)
    assert len(blocks) > 3
    assert sum(block["pieces"] for block in blocks) == len(rows)
    for i in range(75):
        assert any(f"номер {i} про" in block["text"] for block in blocks)


def test_literal_short_quote_is_accepted_when_present():
    block = {"text": "Ми цього не підтримуємо і прямо про це говоримо."}
    proposed = {"topics": [{
        "topic": "Позиція співрозмовника",
        "summary_uk": "Співрозмовник висловив негативну позицію",
        "evidence": "Ми цього не підтримуємо",
    }]}
    checked = _validate_topics(proposed, block)
    assert checked["verified"] is True
    assert checked["topics"][0]["evidence"] == proposed["topics"][0]["evidence"]


def test_unsupported_quote_is_never_marked_verified():
    block = {"text": "Розмова про погоду на вулиці."}
    proposed = {"topics": [{
        "topic": "Непідтверджена тема",
        "summary_uk": "Уривок не підтверджує вигадану подію",
        "evidence": "Підтверджена подія не відбувалася",
    }]}
    assert _validate_topics(proposed, block)["verified"] is False



def test_model_topic_cannot_invent_source_subject_in_description():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{
        "verified": True,
        "topics": [{
            "topic": "Війна та стратегія",
            "evidence": "Ми сьогодні говоримо про каву та сніданок",
        }],
    }]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_source_quote_allows_subject_without_claiming_it_is_central():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{
        "verified": True,
        "topics": [{
            "topic": "Розмова",
            "evidence": "Ми обговорюємо війну і людські рішення",
        }],
    }]}
    description = _deterministic_evidence_description("", report)
    assert "війна" in description
    assert "стратегічні рішення" not in description
    assert "центральна тема" not in description



def test_long_video_evidence_prompt_is_bounded_and_spans_timeline():
    from rg_youtube_control.dialogue_seo import evidence_outline_text
    report = {"blocks": [
        {
            "verified": True,
            "start_stamp": f"{i:02d}:00:00",
            "topics": [{
                "topic": f"Тема {i}",
                "summary_uk": "Обговорення перевіреної репліки про запитання",
                "evidence": f"Цитата з частини {i} із перевіреного відео",
            }],
        } for i in range(120)
    ]}
    outline = evidence_outline_text(report, max_chars=2400)
    assert len(outline) <= 2400
    assert "Тема 0" in outline
    assert "Тема 119" in outline
    assert "ВИБІРКА ДОКАЗІВ" in outline
    full_outline = evidence_outline_text(report)
    assert len(full_outline) > len(outline)
    assert "Тема 60" in full_outline


def test_single_long_quote_never_breaks_evidence_budget():
    from rg_youtube_control.dialogue_seo import evidence_outline_text
    report = {"blocks": [{
        "verified": True,
        "start_stamp": "00:01:00",
        "topics": [{
            "topic": "Розмова",
            "summary_uk": "Детальна цитата співрозмовника",
            "evidence": "слово " * 300,
        }],
    }]}
    outline = evidence_outline_text(report, max_chars=500)
    assert len(outline) <= 500



def test_editorial_synopsis_does_not_append_unverified_topic_labels():
    from rg_youtube_control.dialogue_seo import preserve_outline_topics
    public_description = (
        "Співрозмовник розповідає про економічні труднощі та їхній вплив "
        "на життя людей. У розмові звучать конкретні приклади й запитання. "
        "Окремі судження учасників залишаються їхніми оцінками."
    )
    report = {"blocks": [
        {
            "verified": True,
            "start_stamp": f"00:{i:02d}:00",
            "topics": [{
                "topic": f"Вигадана модельна тема {i}",
                "evidence": f"Власні слова учасника номер {i}",
            }],
        } for i in range(25)
    ]}
    result, omitted = preserve_outline_topics(
        public_description, report, max_topic_bullets=0, max_body_bytes=900,
    )
    assert result == public_description
    assert omitted
    assert "Інші підтверджені теми" not in result



def test_generic_reason_does_not_become_career_change_claim():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{
        "verified": True,
        "topics": [{
            "topic": "Причини кадрових змін",  # invented model label
            "evidence": "Я хочу зрозуміти причини цієї погоди",
        }],
    }]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_mention_of_war_does_not_claim_strategy():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{
        "verified": True,
        "topics": [{
            "topic": "Стратегічні рішення",
            "evidence": "Ця війна впливає на наше життя",
        }],
    }]}
    description = _deterministic_evidence_description("", report)
    assert "війна" in description
    assert "стратегічні рішення" not in description



def test_ordinary_possessive_pronoun_is_not_war_evidence():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Війна проти України",
        "evidence": "Я люблю свою каву та сніданок",
    }]}]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_foreign_president_is_not_automatically_putin():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Путін та оцінка влади",
        "evidence": "Президент Франції виступив із промовою",
    }]}]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_ukraine_mention_is_not_automatically_war_claim():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Війна",
        "evidence": "В Україні сьогодні дуже гарна погода",
    }]}]}
    description = _deterministic_evidence_description("", report)
    assert "Україна" in description
    assert "війна" not in description



def test_defense_word_does_not_invent_ministry():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Міністерство оборони РФ",
        "evidence": "Оборона міста тривала декілька днів",
    }]}]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_corruption_quote_does_not_invent_officials():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Чиновники та відповідальність",
        "evidence": "Ми обговорили питання корупції",
    }]}]}
    description = _deterministic_evidence_description("", report)
    assert "корупція" in description
    assert "відповідальність чиновників" not in description



def test_robot_is_not_human_employment_topic():
    import pytest
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Робота та зайнятість",
        "evidence": "Робот рухався лабораторією",
    }]}]}
    with pytest.raises(ValueError, match="No editorial subjects"):
        _deterministic_evidence_description("", report)


def test_salary_quote_does_not_claim_other_incomes():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Зарплати та доходи",
        "evidence": "Мені підвищили зарплату цього місяця",
    }]}]}
    description = _deterministic_evidence_description("", report)
    assert "зарплати" in description
    assert "та доходи" not in description


def test_pension_quote_does_not_invent_social_benefits():
    from rg_youtube_control.free_tools import _deterministic_evidence_description
    report = {"blocks": [{"verified": True, "topics": [{
        "topic": "Пенсії та соціальні виплати",
        "evidence": "Ми говорили про розмір пенсії",
    }]}]}
    description = _deterministic_evidence_description("", report)
    assert "пенсії" in description
    assert "соціальні виплати" not in description



def test_reviewer_rejects_revision_with_invalid_editorial_format(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    revised = {
        "title": "Чому співрозмовник змінив думку?",
        "title_variants": ["Лише один варіант"],
        "description": "Занадто короткий опис",
        "tags": ["розмова"],
    }
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *a, **k: json.dumps(revised))
    draft = {
        "title": "Стара назва",
        "description": "Старий опис",
        "title_variants": ["A", "B", "C"],
        "tags": ["тема"],
    }
    report = editor.revise_seo_candidate(
        draft=draft,
        source_notes=[{"time": "00:00:01", "quote": "Ми розмовляли"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": []},
    )
    assert report["revised"] is False
    assert report["editorial_approved"] is False


def test_reviewer_rejects_revision_still_flagged_as_defective(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    revised = {
        "title": "Що обговорюють учасники розмови?",
        "title_variants": [
            "Про що говорять співрозмовники?",
            "Що стало темою обговорення?",
            "Які запитання прозвучали у діалозі?",
        ],
        "description": (
            "Співрозмовники обговорюють запитання та висловлюють думки. "
            "У записі вони пояснюють власні позиції, сперечаються про "
            "аргументи й уточнюють зміст окремих висловлювань. "
        ) * 3,
        "tags": [
            "чат рулетка", "раша гудбай", "український канал",
            "розмова", "дискусія", "співрозмовники",
            "запитання", "відповіді",
        ],
    }
    monkeypatch.setattr(editor, "lm_studio_chat", lambda *a, **k: json.dumps(revised))
    monkeypatch.setattr(
        editor, "review_seo_candidate",
        lambda **k: {"review_status": "NEEDS_REVISION", "issues": [{"field": "title", "reason": "unsupported"}]},
    )
    report = editor.revise_seo_candidate(
        draft={"title": "Стара назва", "description": "Старий опис"},
        source_notes=[{"time": "00:00:01", "quote": "Ми розмовляли"}],
        first_review={"review_status": "NEEDS_REVISION", "issues": []},
    )
    assert report["revised"] is False
    assert report["publication_allowed"] is False



def test_independent_reviewer_rejects_forbidden_approval(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    monkeypatch.setattr(
        editor, "lm_studio_chat",
        lambda *args, **kwargs: json.dumps({
            "verdict": "approved", "issues": [], "recommended_changes": [],
        }),
    )
    review = editor.review_seo_candidate(
        draft={"title": "Заголовок"},
        source_notes=[{"quote": "Слова учасника"}],
    )
    assert review["review_status"] == "REVIEWER_FAILED"
    assert review["editorial_approved"] is False


def test_independent_reviewer_rejects_missing_verdict(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    monkeypatch.setattr(
        editor, "lm_studio_chat",
        lambda *args, **kwargs: json.dumps({
            "issues": [], "recommended_changes": [],
        }),
    )
    review = editor.review_seo_candidate(
        draft={"title": "Заголовок"},
        source_notes=[{"quote": "Слова учасника"}],
    )
    assert review["review_status"] == "REVIEWER_FAILED"


def test_independent_reviewer_blocks_language_warning(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    monkeypatch.setattr(
        editor, "lm_studio_chat",
        lambda *args, **kwargs: json.dumps({
            "verdict": "review", "issues": [],
            "recommended_changes": ["почему это произошло"],
        }),
    )
    review = editor.review_seo_candidate(
        draft={"title": "Заголовок"},
        source_notes=[{"quote": "Слова учасника"}],
    )
    assert review["review_status"] == "NEEDS_REVISION"


def test_independent_reviewer_accepts_valid_review_only(monkeypatch):
    import json
    from rg_youtube_control import seo_editorial_reviewer as editor
    monkeypatch.setattr(
        editor, "lm_studio_chat",
        lambda *args, **kwargs: json.dumps({
            "verdict": "review", "issues": [], "recommended_changes": [],
        }),
    )
    review = editor.review_seo_candidate(
        draft={"title": "Заголовок"},
        source_notes=[{"quote": "Слова учасника"}],
    )
    assert review["review_status"] == "NEEDS_HUMAN_REVIEW"
    assert review["publication_allowed"] is False



def test_independent_reviewer_source_notes_span_full_video_and_preserve_time():
    from rg_youtube_control.seo_editorial_reviewer import (
        select_independent_source_notes,
    )
    report = {"blocks": [
        {
            "verified": True,
            "start_stamp": f"{i:02d}:00:00",
            "topics": [
                {"topic": f"Тема {i}", "evidence": f"Дослівні слова {i}"},
                {"topic": f"Друга тема {i}", "evidence": f"Друга цитата {i}"},
            ],
        } for i in range(60)
    ]}
    notes = select_independent_source_notes(report)
    assert len(notes) == 40
    assert notes[0]["time"] == "00:00:00"
    assert notes[23]["time"] == "59:00:00"
    assert any(note["topic"].startswith("Друга тема") for note in notes)
    assert all(note["time"] and note["quote"] for note in notes)


def test_independent_reviewer_never_uses_unverified_blocks():
    from rg_youtube_control.seo_editorial_reviewer import (
        select_independent_source_notes,
    )
    report = {"blocks": [
        {"verified": False, "start_stamp": "00:00", "topics": [
            {"topic": "Неперевірена", "evidence": "Модельна цитата"},
        ]},
        {"verified": True, "start_stamp": "01:00", "topics": [
            {"topic": "Перевірена", "evidence": "Справжня цитата"},
        ]},
    ]}
    notes = select_independent_source_notes(report)
    assert len(notes) == 1
    assert notes[0]["time"] == "01:00"


def test_short_caption_rescue_keeps_last_subject_word():
    """Short ASR cues are evidence, and their final topic word matters."""
    import json
    from rg_youtube_control.dialogue_seo import analyze_all_timeline_blocks

    quote = "Говорили про ціни на продукти"
    def local_model(messages, **kwargs):
        if "ДОСЛІВНИЙ evidence" in messages[-1]["content"]:
            return json.dumps({"topics": [{
                "topic": "Ціни на продукти",
                "summary_uk": "Учасники прямо говорять про ціни на продукти.",
                "evidence": quote,
            }]}, ensure_ascii=False)
        return json.dumps({"topics": []})

    report = analyze_all_timeline_blocks(
        [{"start": 0.0, "duration": 2.0, "text": quote}],
        model="unit-test", chat=local_model,
    )
    assert report["blocks_total"] == 1
    assert report["blocks_with_evidence"] == 1
    assert report["unverified_blocks"] == []
    assert report["blocks"][0]["topics"][0]["evidence"] == quote


def test_russian_phrase_tags_rejected_in_ukrainian_seo():
    from rg_youtube_control.seo_quality_gate import language_error
    for tag in (
        "Украина стала Россией",
        "кто поддерживает войну",
        "голосовать за Путина",
        "реакция россиянина",
        "после мобилизации",
        "дети или алкоголь",
    ):
        assert language_error(tag), tag
    for tag in (
        "Україна та Росія",
        "мобілізація в Росії",
        "війна Росії проти України",
        "реакція росіянина",
        "діти та алкоголь",
    ):
        assert not language_error(tag), tag


def test_one_vague_ab_title_is_not_editorial_quality_pass():
    from rg_youtube_control.free_tools import _seo_editorial_preview_flags
    variants = [
        "Путін: що говорять співрозмовники?",
        "Мобілізація: небажання чоловіків їхати на фронт",
        "Вибори: росіянин заявив, що голосуватиме за Путіна",
    ]
    assert "GENERIC_AB_VARIANTS" in _seo_editorial_preview_flags(
        "Росіянин про війну і вибори", "", variants, [],
    )
    specific = [
        "Росіянин заявив, що голосуватиме за Путіна",
        "«У нас війни немає»: як співрозмовник заперечує війну",
        "Чоловіки не хотіли їхати після мобілізації: слова росіянина",
    ]
    assert "GENERIC_AB_VARIANTS" not in _seo_editorial_preview_flags(
        "Росіянин про війну і вибори", "", specific, [],
    )
