"""Checks bugs previously discovered only after installing the Windows app."""
import json

import pytest

from rg_youtube_control.seo_engine_v1 import generate_draft

VIDEO = "UC-zGLdheCE"
TITLE = "Могут ли ОСУЖДЕННЫЕ за тяжкие преступления преподавать в ШКОЛАХ РФ?"
TRANSCRIPT = ("Осужденные за тяжкие преступления и школы России. "
              "Как могут преподавать учителя с судимостью? " * 9)
DESCRIPTION = ("У цьому випуску обговорюємо роботу засуджених педагогів "
               "у школах, безпеку дітей та позицію батьків. " * 5)
TAGS = ["раша гудбай", "чат рулетка", "школы россии", "осужденные",
        "судимость", "учителя", "педагоги", "россияне"]


def candidate(tags=TAGS):
    return json.dumps({
        "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РЕАКЦИЯ РОССИЯН",
        "ab_titles": ["Осужденные и школа: реакция родителей",
                      "Учителя с судимостью: споры в России",
                      "Преподавание после тяжкого преступления?"],
        "description": DESCRIPTION,
        "tags": tags,
        "chapters": "",
    }, ensure_ascii=False)


def test_eight_unique_tags_matches_ui_contract():
    draft = generate_draft(video_id=VIDEO, current_title=TITLE,
                           transcript=TRANSCRIPT,
                           generate_json=lambda _: candidate())
    assert len(draft.tags) == 8
    assert draft.needs_review


def test_three_tags_rejected_before_ui():
    with pytest.raises(ValueError, match="Tags invalid"):
        generate_draft(video_id=VIDEO, current_title=TITLE,
                       transcript=TRANSCRIPT,
                       generate_json=lambda _: candidate(TAGS[:3]))


def test_duplicate_tags_rejected_before_ui():
    with pytest.raises(ValueError, match="eight unique tags"):
        generate_draft(video_id=VIDEO, current_title=TITLE,
                       transcript=TRANSCRIPT,
                       generate_json=lambda _: candidate(TAGS[:7] + [TAGS[0]]))


def test_unrelated_model_response_rejected():
    bad = json.loads(candidate())
    bad["title"] = "КАК РОССИЯНЕ ПРОВЕРЯЮТ НОВОСТИ?"
    bad["description"] = "Проверяем фейковые новости. " * 35
    with pytest.raises(ValueError, match="SEO_TOPIC_MISMATCH"):
        generate_draft(video_id=VIDEO, current_title=TITLE,
                       transcript=TRANSCRIPT,
                       generate_json=lambda _: json.dumps(bad, ensure_ascii=False))


def test_invalid_chapter_timestamp_rejected():
    item = json.loads(candidate())
    item["chapters"] = "00:72 Вопрос о школах"
    with pytest.raises(ValueError, match="Invalid chapter timestamp"):
        generate_draft(video_id=VIDEO, current_title=TITLE,
                       transcript=TRANSCRIPT,
                       generate_json=lambda _: json.dumps(item, ensure_ascii=False))


def test_chapters_must_have_real_timestamps():
    item = json.loads(candidate())
    item["chapters"] = "Вступление и обсуждение"
    with pytest.raises(ValueError, match="Invalid chapters format"):
        generate_draft(video_id=VIDEO, current_title=TITLE,
                       transcript=TRANSCRIPT,
                       generate_json=lambda _: json.dumps(item, ensure_ascii=False))
