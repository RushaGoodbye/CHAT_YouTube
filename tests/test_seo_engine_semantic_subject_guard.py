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
