"""Operator regression: a random appearance quote must never become title #4.

Mock only external Ollama and unrelated tag/chapter producers. Run the actual
generator, content-grounding and A/B review gates in-process.
"""
import json

from rg_youtube_control import free_tools as seo


def test_operator_appearance_hook_is_never_in_primary_or_ab(monkeypatch):
    published = (
        "Увольнение ШОЙГУ - коррупция или все идет по плану? | РАША ГУДБАЙ"
    )
    model_payload = {
        "title": "Ты выглядишь красиво! Шокирующий ответ россиянки",
        "title_variants": [
            "Шойгу и коррупция в армии: всё идет по плану?",
            "Разговор про войну и коррупцию в России",
            "Твоя внешность удивила всех зрителей!",
        ],
        "description": (
            "У цьому випуску учасники сперечаються про рішення влади, "
            "кадрові зміни й корупцію. Співрозмовники висловлюють "
            "свої думки про причини рішень."
        ),
        "tags": [
            "раша гудбай", "чат рулетка", "Шойгу", "коррупция в армии",
            "министр обороны", "военная стратегия", "армия России",
            "Путин и Шойгу", "новости России", "смена министра",
        ],
        "chapters": "",
    }
    report = {
        "blocks_total": 4,
        "blocks_with_evidence": 4,
        "blocks": [
            {"verified": True, "start_stamp": "00:00:00", "topics": [
                {"topic": "Зміни в обороні",
                 "evidence": "Шойгу уволили из-за коррупции в армии или нет?",
                 "summary_uk": "Учасники обговорюють кадрові зміни."}]},
            {"verified": True, "start_stamp": "00:04:00", "topics": [
                {"topic": "Війна і рішення",
                 "evidence": "Война продолжается и стратегию министров обсуждают.",
                 "summary_uk": "Учасники сперечаються про стратегію."}]},
            {"verified": True, "start_stamp": "00:09:00", "topics": [
                {"topic": "Побічна репліка",
                 "evidence": "Ты выглядишь очень красиво, какая внешность!",
                 "summary_uk": "Побічна розмова про зовнішність."}]},
            {"verified": True, "start_stamp": "00:12:00", "topics": [
                {"topic": "Корупція",
                 "evidence": "Коррупция в министерстве это большой вопрос.",
                 "summary_uk": "Позиції щодо корупції."}]},
        ],
    }
    monkeypatch.setattr(
        seo, "ollama_chat",
        lambda *args, **kw: json.dumps(model_payload, ensure_ascii=False),
    )
    monkeypatch.setattr(
        seo, "_recover_title_variants",
        lambda **kw: list(model_payload["title_variants"]),
    )
    monkeypatch.setattr(
        seo, "_recover_independent_ab_titles",
        lambda **kw: list(model_payload["title_variants"]),
    )
    monkeypatch.setattr(
        seo, "_tag_is_grounded",
        lambda tag, current_title, transcript: True,
    )

    result = seo.generate_seo_package_local(
        current_title=published,
        transcript=seo.evidence_outline_text(report),
        public_context={"title": published},
        evidence_report=report,
        is_short=True,
    )

    shown_titles = [result["title"]] + result["title_variants"]
    assert result["title"] == published
    assert len(shown_titles) <= 4
    assert not any(seo._incidental_ab_quote(t) for t in shown_titles)
    assert result["needs_review"] is True
    assert "Побічну репліку" in result["review_reason"]
    assert result["youtube_data_api_quota"] == 0


def test_substantive_title_not_rejected_by_appearance_guard():
    assert not seo._incidental_ab_quote(
        "Шойгу и коррупция: кто отвечает за решения Минобороны?"
    )
