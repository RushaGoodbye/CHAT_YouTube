"""Automatic bounded retries must not hide invalid source or cause repeat loops."""
import json
import pytest

from rg_youtube_control import seo_engine_ollama as module
from rg_youtube_control.seo_engine_v1 import generate_draft


VID = "UC-zGLdheCE"
TITLE = "Могут ли ОСУЖДЕННЫЕ преподавать в ШКОЛАХ РФ?"
SOURCE = (
    "Осужденные за тяжкие преступления и безопасность детей в школах РФ. "
    "Родители обсуждают учителей с судимостью и преподавание. " * 9
)


def candidate(tags):
    return json.dumps({
        "title": "СУДИМЫЕ УЧИТЕЛЯ В ШКОЛАХ РФ? РОССИЯНЕ СПОРЯТ",
        "ab_titles": ["Судимые учителя: реакция родителей",
                      "Педагоги с судимостью: что говорят россияне",
                      "Осужденные и школы: можно ли доверять детей?"],
        "description": ("Росіяни обговорюють, чи можуть засуджені люди "
                        "працювати в школах і як захистити дітей. " * 6),
        "tags": tags,
        "chapters": "",
    }, ensure_ascii=False)


TAGS = ["раша гудбай", "чат рулетка", "судимость", "школы россии",
        "осужденные", "педагоги", "учителя", "россияне"]


def test_one_repair_recovers_bad_tag_count(monkeypatch):
    prompts = []
    def fake_llm(prompt, *, model):
        prompts.append(prompt)
        return candidate(TAGS[:3] if len(prompts) == 1 else TAGS)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    draft = module.generate_with_ollama(
        video_id=VID, current_title=TITLE, transcript=SOURCE
    )
    assert len(draft.tags) == 8
    assert len(prompts) == 2
    assert "ПОПЕРЕДНЯ ВІДПОВІДЬ" in prompts[1]


def test_never_retries_source_title_mismatch(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        return candidate(TAGS)
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    with pytest.raises(ValueError, match="SOURCE_VIDEO_MISMATCH"):
        module.generate_with_ollama(
            video_id=VID, current_title=TITLE,
            transcript="Разговор о погоде и ремонте автомобилей. " * 10,
        )
    assert count == 1


def test_no_infinite_retry_on_repeated_malformed_model(monkeypatch):
    count = 0
    def fake_llm(prompt, *, model):
        nonlocal count
        count += 1
        return candidate(TAGS[:3])
    monkeypatch.setattr(module, "ollama_json", fake_llm)
    with pytest.raises(ValueError, match="Tags invalid"):
        module.generate_with_ollama(
            video_id=VID, current_title=TITLE, transcript=SOURCE
        )
    assert count == 2
