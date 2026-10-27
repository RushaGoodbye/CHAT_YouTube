"""Ground topic continuity across RU inflection while rejecting real drift.

Covers two actual AlexPC diagnostic reports; no source transcript content.
"""
import pytest
from rg_youtube_control.seo_engine_v1 import (
    _topic_roots, _check_editorial_title,
)


def test_27_years_without_change_matches_no_changes():
    original = "27 лет ничего не менять - и считать себя против войны"
    proposed = "Коллективная ответственность России за войну: 27 лет без изменений"
    source = (
        "Граждане 27 лет ничего не хотят менять. Кто отвечает за войну? "
        "Говорят, что не меняли политическую систему все эти годы. " * 12
    )
    assert {"change", "war"}.issubset(_topic_roots(original))
    assert {"change", "war"}.issubset(_topic_roots(proposed))
    _check_editorial_title(original, proposed, source)


def test_fishing_and_jedi_cannot_become_mushrooms_and_politics():
    original = "ЧАТ РУЛЕТКА РАША ГУДБАЙ. ФАНТАЗЁРЫ из рф - РЫБАК и ДЖЕДАЙ"
    proposed = "ЧАТ О ПОЛЕНЕ, ГРИБАХ И ПОЛИТИКЕ"
    source = (
        "Рыбак спорит с джедаем в чат рулетке, фантазер рассказывает истории. "
        "Он упомянул грибы, полено и политику в конце беседы. " * 12
    )
    with pytest.raises(ValueError, match="SEO_TOPIC_MISMATCH"):
        _check_editorial_title(original, proposed, source)


def test_original_school_crime_topic_is_not_replaced_with_entertainment():
    source = (
        "Школы, учителя с судимостью, осужденные за преступления, дети. " * 14
    )
    with pytest.raises(ValueError, match="SEO_TOPIC_MISMATCH"):
        _check_editorial_title(
            "Могут ли осужденные преподавать в школах?",
            "Встреча веселых грибников на реке",
            source,
        )



def test_real_27_year_topic_passes_full_source_bound_editorial_gate():
    import json
    from rg_youtube_control.seo_engine_v1 import generate_draft
    original = "27 лет ничего не менять - и считать себя против войны"
    source = (
        "Россияне 27 лет ничего не меняют и говорят, что они против войны. "
        "Собеседник обсуждает ответственность за войну и отсутствие изменений. " * 16
    )
    package = {
        "title": "Коллективная ответственность за войну: 27 лет без изменений",
        "ab_titles": [
            "Почему россияне 27 лет ничего не меняют?",
            "Против войны, но без изменений: позиция россиян",
            "Россияне, война и 27 лет без перемен",
        ],
        "description": (
            "У розмові росіяни обговорюють колективну відповідальність "
            "за війну та причини того, чому багато років нічого не змінюють. "
            "Учасники говорять про суспільну позицію, відповідальність "
            "та наслідки бездіяльності під час війни. " * 3
        ),
        "tags": [
            "раша гудбай", "чат рулетка", "россияне",
            "война", "коллективная ответственность",
            "нет перемен", "27 лет", "антивоенная позиция",
        ],
        "chapters": "",
    }
    draft = generate_draft(
        video_id="u9y_f4HtEbQ", current_title=original, transcript=source,
        generate_json=lambda _: json.dumps(package, ensure_ascii=False),
    )
    assert "27 лет" in draft.title
    assert draft.needs_review is True



def test_russian_antiwar_title_matches_ukrainian_subject_tags():
    from rg_youtube_control.seo_engine_v1 import _topic_roots
    headline = _topic_roots(
        "Коллективная ответственность за войну: 27 лет без изменений"
    )
    for subject in ("війна", "зміни", "відповідальність"):
        assert _topic_roots(subject).intersection(headline), subject


def test_russian_fisherman_title_matches_ukrainian_fishing_keywords():
    from rg_youtube_control.seo_engine_v1 import _topic_roots
    topic = _topic_roots("Рыбак и джедай в абсурдном диалоге")
    assert _topic_roots("рибалка").intersection(topic)
    assert _topic_roots("джедай").intersection(topic)
