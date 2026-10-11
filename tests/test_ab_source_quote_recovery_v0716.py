"""End-to-end A/B recovery regressions from real 50-minute video failure."""
from rg_youtube_control.dialogue_seo import ab_title_issues
from rg_youtube_control.free_tools import (
    _recover_independent_ab_titles,
    _source_quote_ab_titles,
)


def evidence_report():
    return {"blocks": [
        {"start_stamp": "00:00:00", "topics": [{
            "topic": "Загиблі друзі",
            "evidence": "Я похоронил двух друзей которые пошли на войну и обратно уже не вернулись.",
        }]},
        {"start_stamp": "00:08:00", "topics": [{
            "topic": "Мобілізація",
            "evidence": "Мобилизация людей проводится потому что на фронте стало не хватать солдат.",
        }]},
        {"start_stamp": "00:18:00", "topics": [{
            "topic": "Ціни",
            "evidence": "Бензин на заправке подорожал и зарплаты за такими ценами не успевают.",
        }]},
        {"start_stamp": "00:32:00", "topics": [{
            "topic": "Крим",
            "evidence": "Про Крым и события четырнадцатого года мы тогда говорили совсем иначе.",
        }]},
        {"start_stamp": "00:46:00", "topics": [{
            "topic": "Відповідальність",
            "evidence": "Нужно было отвечать за свои решения раньше и не молчать о происходящем.",
        }]},
    ]}


def test_direct_quotes_make_three_distinct_source_grounded_titles():
    report = evidence_report()
    titles = _source_quote_ab_titles(report)
    assert len(titles) == 3
    assert all(30 <= len(title) <= 100 for title in titles)
    assert all("ЧАТ РУЛЕТКА" in title for title in titles)
    assert not ab_title_issues(titles, report)
    for title in titles:
        excerpt = title.split("«", 1)[1].split("»", 1)[0].removesuffix("…")
        assert any(
            excerpt in topic["evidence"]
            for block in report["blocks"] for topic in block["topics"]
        )


def test_partial_model_failure_does_not_discard_all_titles(monkeypatch):
    calls = []
    def unreliable_chat(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("qwen3 temporarily unavailable")
        return '{"title":"Какая ответственность за войну и судьбы людей?"}'
    monkeypatch.setattr("rg_youtube_control.free_tools.ollama_chat", unreliable_chat)
    result = _recover_independent_ab_titles(
        report=evidence_report(), current_title="РАША ГУДБАЙ", model="qwen3:8b",
    )
    assert len(result) == 3
    assert not ab_title_issues(result, evidence_report())


def test_missing_quotes_fail_closed_not_fake_titles():
    report = {"blocks": [
        {"topics": [{"topic": "Загиблі", "evidence": ""}]},
        {"topics": [{"topic": "Економіка", "evidence": ""}]},
        {"topics": [{"topic": "Фронт", "evidence": ""}]},
    ]}
    assert _source_quote_ab_titles(report) == []


def test_repeated_quote_from_three_blocks_not_distinct_stories():
    same = "Человек говорил об экономике и ценах в России вчера вечером."
    report = {"blocks": [
        {"topics": [{"topic": f"Тема {i}", "evidence": same}]}
        for i in range(4)
    ]}
    assert _source_quote_ab_titles(report) == []


def test_short_or_filler_quotes_rejected():
    report = {"blocks": [
        {"topics": [{"topic": f"Розмова {i}", "evidence": "да да ну ладно"}]}
        for i in range(5)
    ]}
    assert _source_quote_ab_titles(report) == []
