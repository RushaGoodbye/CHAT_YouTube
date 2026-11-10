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
