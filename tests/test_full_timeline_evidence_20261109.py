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
    assert "війна та стратегічні рішення" in description
    assert "центральна тема" not in description
