"""Semantic QA regression: review observations do not become source facts."""
from __future__ import annotations

from rg_youtube_control.seo_v2_semantic import (
    independent_review, revise_semantic_defects, unsupported_names,
)


def _proof():
    return [
        {"evidence_id": "ev_1", "quote": "Ведучий запитав про причини звільнення Сидоренка."},
        {"evidence_id": "ev_2", "quote": "Можливо причина в аудиті, це лише моя думка."},
        {"evidence_id": "ev_3", "quote": "Якби це було покарання, йому не довірили б іншу посаду."},
    ]


def _draft():
    return {
        "title": "Справжні причини звільнення Сидаренка: аудит",
        "title_variants": [
            "Чому звільнили Сидаренка?", "Він завершив роботу",
            "Аудит довів причину звільнення",
        ],
        "description": (
            "Аналіз доводить, що аудит став причиною звільнення. "
            "Це виключає покарання як мотив."
        ),
        "tags": ["причини звільнення", "аудит"],
        "support_ids": {
            "title": ["ev_1", "ev_2"],
            "title_variants": [["ev_1"], ["ev_3"], ["ev_2"]],
            "description": ["ev_2", "ev_3"],
            "tags": [["ev_1"], ["ev_2"]],
        },
    }


def test_name_spelling_is_not_accepted_just_because_citation_id_exists():
    problems = unsupported_names(_draft(), _proof())
    assert "Сидаренка" in problems


def test_source_spelling_passes_without_topic_specific_whitelist():
    draft = _draft()
    draft["title"] = "Можливі причини звільнення Сидоренка: думка співрозмовника"
    draft["title_variants"][0] = "Чому звільнили Сидоренка?"
    assert "Сидоренка" not in unsupported_names(draft, _proof())


def test_independent_review_can_flag_inferred_facts_and_name_errors():
    seen = []
    def reviewer(prompt):
        seen.append(prompt)
        assert "uncertain personal names" in prompt
        assert "objective facts" in prompt
        return {"issues": [
            {"field": "description", "reason": "Opinion presented as a proven motive"},
            {"field": "title", "reason": "Name in title differs from original"},
        ]}
    review = independent_review(_draft(), _proof(), reviewer)
    assert len(review["issues"]) == 2
    assert len(seen) == 1


def test_semantic_repair_is_source_only_and_does_not_modify_other_fields():
    draft = _draft()
    def model(prompt):
        assert "ONLY factual" in prompt
        return {
            "changes": {
                "title": "Співрозмовник обговорює звільнення Сидоренка",
                "description": (
                    "У розмові учасник висловлює думку, що можливий аудит "
                    "міг вплинути на рішення. Він не називає це доведеним "
                    "фактом. Інший аргумент стосується посади."
                ),
            },
            "support_ids": {
                "title": ["ev_1"], "description": ["ev_2", "ev_3"]
            },
        }
    issues = {"issues": [
        {"field": "title", "reason": "Name misspelled"},
        {"field": "description", "reason": "Opinion presented as fact"},
    ]}
    result = revise_semantic_defects(draft, _proof(), issues, model)
    assert result is not None
    assert result["tags"] == draft["tags"]
    assert result["title_variants"] == draft["title_variants"]
    assert "Сидоренка" in result["title"]
    assert result["description"] != draft["description"]


def test_semantic_repair_does_not_grant_fake_source_ids():
    response = lambda _p: {
        "changes": {"title": "Виправлено назву"},
        "support_ids": {"title": ["ev_fake"]},
    }
    assert revise_semantic_defects(
        _draft(), _proof(),
        {"issues": [{"field": "title", "reason": "Missing source"}]},
        response,
    ) is None


def test_malformed_independent_review_fails_closed():
    assert independent_review(_draft(), _proof(), lambda _: {"status": "PASS"})[
        "review_status"
    ] == "FAILED_CLOSED"


def test_ukrainian_and_russian_forms_of_same_name_are_accepted():
    from rg_youtube_control.seo_v2_semantic import _same_inflected_name
    assert _same_inflected_name("Іванова", "Иванова")
    assert _same_inflected_name("Путін", "Путин")
    assert _same_inflected_name("Тимур", "Тимура")
    assert _same_inflected_name("Києві", "Киеве")
    assert not _same_inflected_name("Шайгурова", "шайгумаров")
    assert not _same_inflected_name("Сидаренка", "Сидоренка")
