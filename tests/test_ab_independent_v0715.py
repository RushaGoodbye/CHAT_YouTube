"""Independent model calls recover one specific title per verified story."""
import json
from rg_youtube_control import free_tools


def _three_verified_topics():
    return {"blocks": [
        {"start_stamp": "00:01", "topics": [{
            "topic": "Поховання загиблих друзів", "evidence": "Я поховав своїх друзів",
        }]},
        {"start_stamp": "00:20", "topics": [{
            "topic": "Страх перед владою", "evidence": "Люди мовчать через страх",
        }]},
        {"start_stamp": "00:40", "topics": [{
            "topic": "Ціни на паливо", "evidence": "У Волгограді бензин став дорожчим",
        }]},
    ]}


def test_one_independent_title_per_verified_story(monkeypatch):
    calls = []
    responses = [
        "Почему собеседник похоронил друзей на войне?",
        "Страх перед властью: почему люди молчат?",
        "Бензин подорожал: что рассказал житель Волгограда?",
    ]
    def chat(messages, **kwargs):
        prompt = messages[-1]["content"]
        calls.append(prompt)
        return json.dumps({"title": responses[len(calls) - 1]}, ensure_ascii=False)

    monkeypatch.setattr(free_tools, "ollama_chat", chat)
    titles = free_tools._recover_independent_ab_titles(
        report=_three_verified_topics(),
        current_title="Текущая тема о войне и россиянах",
        model="qwen3:8b",
    )
    assert titles == responses
    assert len(calls) == 3
    assert "Поховання загиблих друзів" in calls[0]
    assert "Страх перед владою" in calls[1]
    assert "Ціни на паливо" in calls[2]
    assert all("json_mode" not in prompt for prompt in calls)


def test_missing_evidence_does_not_invent_stories(monkeypatch):
    monkeypatch.setattr(
        free_tools, "ollama_chat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")),
    )
    assert free_tools._recover_independent_ab_titles(
        report={"blocks": [{"topics": [{"topic": "Тема", "evidence": ""}]}]},
        current_title="Текущая тема",
        model="qwen3:8b",
    ) == []


def test_duplicate_model_answer_is_rejected(monkeypatch):
    calls = []
    def chat(*a, **k):
        calls.append(1)
        return json.dumps({"title": "ОДНО И ТО ЖЕ НАЗВАНИЕ ПО ВСЕМ ТРЁМ ТЕМАМ"})

    monkeypatch.setattr(free_tools, "ollama_chat", chat)
    titles = free_tools._recover_independent_ab_titles(
        report=_three_verified_topics(),
        current_title="Текущая тема",
        model="qwen3:8b",
    )
    assert titles == []
    assert len(calls) == 2


def test_empty_model_json_is_never_silently_used(monkeypatch):
    monkeypatch.setattr(free_tools, "ollama_chat", lambda *a, **k: "{}")
    assert free_tools._recover_independent_ab_titles(
        report=_three_verified_topics(),
        current_title="Текущая тема",
        model="qwen3:8b",
    ) == []
