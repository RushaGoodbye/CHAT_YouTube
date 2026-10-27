import json
import pytest

from rg_youtube_control.seo_engine_v1 import generate_draft


TITLE = "Могут ли осужденные за тяжкие преступления преподавать в школах РФ?"
SOURCE = ("Осужденные за тяжкие преступления могут ли работать в школах? "
          "Собеседники обсуждают безопасность детей, учителей с судимостью "
          "и педагогическую деятельность. ") * 6


def model(prompt):
    return json.dumps({
        "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ? РОССИЯНЕ СПОРЯТ | РАША ГУДБАЙ",
        "ab_titles": ["Осужденные и школы РФ: что говорят россияне?",
                      "Преподаватели с судимостью: можно ли доверять детей?",
                      "Российские школы и тяжкие преступления: реакция людей"],
        "description": ("У чат-рулетці росіяни обговорюють, чи можуть засуджені "
                        "викладати у школах РФ. Вони говорять про безпеку "
                        "дітей, вимоги до педагогів, судимості й тяжкі "
                        "злочини, а також про різні погляди на другий шанс. "
                        "Слова учасників — їхні власні думки, а не "
                        "встановлені юридичні факти. ") * 2,
        "tags": ["раша гудбай", "чат рулетка", "школы россии", "учителя", "осужденные", "судимость", "педагоги", "россияне"],
        "chapters": "00:00 Вопрос о преподавателях"
    }, ensure_ascii=False)


def test_school_discussion_creates_complete_review_only_package():
    draft = generate_draft(video_id="UC-zGLdheCE",
                           current_title=TITLE, transcript=SOURCE,
                           generate_json=model)
    assert draft.needs_review is True
    assert len(draft.ab_titles) == 3
    assert len(draft.description) >= 260
    assert "ШКОЛАХ" in draft.title


def test_cross_video_transcript_is_rejected():
    with pytest.raises(ValueError, match="SOURCE_VIDEO_MISMATCH"):
        generate_draft(
            video_id="UC-zGLdheCE", current_title=TITLE,
            transcript=("Разговор о погоде, автомобиле и музыке. " * 10),
            generate_json=model,
        )


def test_invalid_json_is_not_accepted():
    with pytest.raises(json.JSONDecodeError):
        generate_draft(video_id="UC-zGLdheCE",
                       current_title=TITLE, transcript=SOURCE,
                       generate_json=lambda _: "{bad")
