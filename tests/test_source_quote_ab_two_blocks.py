"""Regression: two caption windows can still contain three independent quotes."""
from rg_youtube_control import free_tools


def test_quote_fallback_uses_distinct_topics_not_timeline_block_count(monkeypatch):
    report = {"blocks": [
        {"verified": True, "start_stamp": "00:00", "topics": [
            {"topic": "Тема A", "evidence": "Обговорюємо конкретне питання першої частини розмови про події."},
            {"topic": "Тема B", "evidence": "Друга цитата містить зовсім інший аргумент співрозмовника про рішення."},
        ]},
        {"verified": True, "start_stamp": "05:00", "topics": [
            {"topic": "Тема C", "evidence": "Третя цитата містить окреме питання про наслідки відомих подій."},
        ]},
    ]}
    monkeypatch.setattr(free_tools, "ab_title_issues", lambda titles, report: [])
    titles = free_tools._source_quote_ab_titles(report, "")
    assert len(titles) == 3
    assert all(title.startswith("«") and title.endswith(" | ЧАТ РУЛЕТКА") for title in titles)
    assert len(set(titles)) == 3


def test_quote_fallback_never_fabricates_third_topic(monkeypatch):
    report = {"blocks": [
        {"verified": True, "start_stamp": "00:00", "topics": [
            {"topic": "Тема A", "evidence": "Достатньо довга перша цитата про відому ситуацію і точні події."}
        ]},
        {"verified": True, "start_stamp": "05:00", "topics": [
            {"topic": "Тема B", "evidence": "Достатньо довга друга цитата про окреме рішення та розмову."}
        ]},
    ]}
    monkeypatch.setattr(free_tools, "ab_title_issues", lambda titles, report: [])
    assert free_tools._source_quote_ab_titles(report, "") == []
