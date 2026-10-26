"""One comprehensive gate for the full SEO Engine v1 contract.

Run before ANY Windows installer or user acceptance.
Pure offline tests: no model, YouTube, DB, or PC changes.
"""
import json
import pytest
from rg_youtube_control.seo_engine_v1 import generate_draft
from rg_youtube_control.seo_engine_ollama import SCHEMA

VID="UC-zGLdheCE"
TITLE="Могут ли ОСУЖДЕННЫЕ за тяжкие преступления преподавать в ШКОЛАХ РФ?"
SOURCE=("Осужденные за тяжкие преступления могут ли преподавать в школах России? "
        "Родители обсуждают доверие учителям, безопасность детей и требования к педагогам. ")*8
TITLE_GOOD="СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РОССИЯНЕ СПОРЯТ"
TAGS=["раша гудбай","чат рулетка","школы россии","осужденные","судимость",
      "учителя","педагоги","россияне"]
DESC=("У цьому випуску обговорюють засуджених викладачів у школах, "
      "ставлення росіян до судимих учителів, безпеку дітей та думки батьків. ")*5

def good():
    return dict(title=TITLE_GOOD,
      ab_titles=["Осужденные и школы: аргументы россиян?",
                 "Судимые педагоги: реакция родителей",
                 "Школы России и учителя после тяжкого преступления"],
      description=DESC,tags=TAGS.copy(),chapters="00:00 Вступление\n01:25 Школы")

def run(data,*,source=SOURCE):
    return generate_draft(video_id=VID,current_title=TITLE,transcript=source,
                          generate_json=lambda _: json.dumps(data,ensure_ascii=False))

def test_complete_contract_and_schema_agree():
    d=run(good())
    assert d.needs_review and len(d.ab_titles)==3 and len(d.tags)>=8
    assert SCHEMA["properties"]["tags"]["minItems"]==8
    assert SCHEMA["properties"]["ab_titles"]["minItems"]==3

@pytest.mark.parametrize("mutation,pattern",[
    ({"title":""},"Invalid primary title"),
    ({"title":"x"*101},"Invalid primary title"),
    ({"ab_titles":[]},"Exactly three"),
    ({"ab_titles":["a","b","c","d"]},"Exactly three"),
    ({"ab_titles":[TITLE_GOOD,"a","b"]},"A/B titles are duplicates"),
    ({"description":"short"},"Description length"),
    ({"tags":TAGS[:3]},"Tags invalid"),
    ({"tags":TAGS[:7]+[TAGS[0]]},"eight unique tags"),
    ({"tags":[x*40 for x in TAGS]},"Tag text exceeds"),
    ({"chapters":"00:76 impossible"},"Invalid chapter timestamp"),
    ({"chapters":"chapter without time"},"Invalid chapters format"),
    ({"title":"ФЕЙКОВЫЕ НОВОСТИ В РОССИИ?","description":"Фейки в новостях. "*50},
     "SEO_TOPIC_MISMATCH"),
])
def test_bad_outputs_are_blocked_in_single_gate(mutation,pattern):
    data=good()
    data.update(mutation)
    with pytest.raises(ValueError,match=pattern):
        run(data)

def test_unrelated_caption_source_blocked():
    with pytest.raises(ValueError,match="SOURCE_VIDEO_MISMATCH"):
        run(good(),source="Разговор о погоде и концерте, музыке и фильмах. "*12)

@pytest.mark.parametrize("bad_id",["","invalid","UC/zGLdheCE","UC-zGLdheCE!"])
def test_bad_video_ids_blocked(bad_id):
    with pytest.raises(ValueError,match="Invalid YouTube Video ID"):
        generate_draft(video_id=bad_id,current_title=TITLE,transcript=SOURCE,
                       generate_json=lambda _: json.dumps(good(),ensure_ascii=False))

def test_invalid_model_output_blocked():
    with pytest.raises(json.JSONDecodeError):
        generate_draft(video_id=VID,current_title=TITLE,transcript=SOURCE,
                       generate_json=lambda _: "{ broken")
